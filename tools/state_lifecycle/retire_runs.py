"""retire_runs.py — retire a superseded run: archive its row to a cold parquet,
drop the live ledger row (authorized operator-cleanup), and prune its heavy
artifacts.

Context (rerun-backtest Phase C)
--------------------------------
A rerun *replaces* its predecessor with a new ``run_id`` and supersedes the old
row (``is_current=0``). Once the new run exists, the old run's heavy artifacts
(``runs/<run_id>/``, ``backtests/<name>/``) are dead weight — the old row is
never promoted, never executed, never a rollback target. This tool trims the
predecessor, **per batch, after** the rerun lands.

It does three things per ``run_id``, in this order:

  1. ARCHIVE   — append the run's compact metrics to the cold archive
                 ``TradeScan_State/retired/retired_runs.parquet`` (append-only,
                 deduped by run_id). This is the queryable "what-we-tried-and-
                 retired" base — it feeds the F19 don't-re-test guard without
                 keeping artifacts.
  2. DROP      — remove the live ledger row. This is the ONLY sanctioned ledger-
                 row removal (Invariant #2, append-only ledgers) and is done the
                 authorized operator-cleanup way: back up ledger.db first, scope
                 by the EXACT run_id, and refuse anything whose is_current is not
                 explicitly 0 (never drops a live row). Archive-BEFORE-drop makes
                 it a *move* to cold storage, never a destroy.
  3. PRUNE     — move ``runs/<run_id>/`` and the run's ``backtests/`` capsule to
                 ``quarantine/retired/`` (recoverable; deletable in bulk later).

Safety invariants (the dangerous part)
--------------------------------------
  * DRY-RUN IS THE DEFAULT. Nothing mutates without ``--execute``.
  * A row is retired ONLY if its ``is_current`` resolves to explicit 0. NULL or 1
    (= current) is REFUSED — we never drop a live run.
  * A successor must exist (``superseded_by`` set) unless ``--force``.
  * ledger.db is backed up (timestamped ``.bak_*``) before the first DROP.
  * The DELETE is scoped by exact run_id AND re-guarded ``is_current=0`` in SQL;
    rowcount must be exactly 1 or the drop aborts.
  * Idempotent — a run already in the archive is not re-archived; a missing row /
    missing artifact is a no-op, not an error.

CLI
---
    # Dry-run (default) — show what would happen, write nothing:
    python tools/state_lifecycle/retire_runs.py --run-ids <id1,id2,...>

    # Execute:
    python tools/state_lifecycle/retire_runs.py --run-ids <id1,id2,...> --execute

    # Drift check (read-only) — superseded runs with on-disk artifacts not yet
    # archived (skipped retirements):
    python tools/state_lifecycle/retire_runs.py --drift-check [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Tables that hold runs, in the order we probe them for a handle.
_LEDGER_TABLES = ("master_filter", "cointegration_sheet", "basket_sheet")


# ── Path resolvers (call-time, so tests can monkeypatch TRADE_SCAN_STATE) ────

def _state_root() -> Path:
    import config.path_authority as pa

    return Path(pa.TRADE_SCAN_STATE)


def _ledger_db() -> Path:
    return _state_root() / "ledger.db"


def _runs_dir() -> Path:
    return _state_root() / "runs"


def _backtests_dir() -> Path:
    return _state_root() / "backtests"


def _quarantine_dir() -> Path:
    return _state_root() / "quarantine" / "retired"


def _retired_parquet() -> Path:
    return _state_root() / "retired" / "retired_runs.parquet"


def _audit_log() -> Path:
    return PROJECT_ROOT / "outputs" / "logs" / "retire_audit.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── is_current parsing (INTEGER in prod, TEXT in fixtures, NULL = current) ───

def _is_superseded(val: Any) -> bool:
    """True iff ``val`` is an explicit 0 (superseded). NULL / 1 / unparseable
    are treated as NOT superseded (= current) — we never retire those."""
    if val is None:
        return False
    try:
        return float(val) == 0.0
    except (TypeError, ValueError):
        return False


def _has_successor(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and s.lower() not in ("none", "nan", "null")


# ── Row lookup + compact projection ─────────────────────────────────────────

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        cur = conn.execute(f'PRAGMA table_info("{table}")')
        return {r[1] for r in cur.fetchall()}
    except sqlite3.Error:
        return set()


def _find_run_row(conn: sqlite3.Connection, run_id: str):
    """Return ``(table, row_dict)`` for the run, probing all three sheets.
    Returns ``(None, None)`` if no table holds it."""
    conn.row_factory = sqlite3.Row
    for table in _LEDGER_TABLES:
        cols = _table_columns(conn, table)
        if "run_id" not in cols:
            continue
        try:
            cur = conn.execute(
                f'SELECT * FROM "{table}" WHERE run_id = ? LIMIT 1', (run_id,)
            )
            row = cur.fetchone()
        except sqlite3.Error:
            continue
        if row is not None:
            return table, dict(row)
    return None, None


def _pick(row: dict, *keys):
    """First non-None value among ``keys`` in ``row``."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            return v
    return None


def _pair_or_symbol(row: dict):
    a, b = row.get("pair_a"), row.get("pair_b")
    if a and b:
        return f"{a}/{b}"
    return _pick(row, "basket_id", "symbol")


def _compact_record(table: str, row: dict) -> dict:
    """Project a run row down to the cold-archive schema (tolerant of which
    sheet it came from)."""
    # Column names differ per sheet (verified against the live schemas):
    #   cointegration_sheet: canonical_net_pct / canonical_ret_dd / canonical_max_dd_pct
    #                        / canonical_final_equity_usd / trades_total / cycles_completed
    #                        / engine_version / test_start / test_end / pair_a,pair_b
    #   basket_sheet:        canonical_* + final_realized_usd / basket_id / completed_at_utc (no test_start)
    #   master_filter:       total_net_profit / return_dd_ratio / max_dd_pct / total_trades
    #                        / profit_factor / symbol (no canonical_*, no engine_version)
    return {
        "run_id": row.get("run_id"),
        "directive_id": _pick(row, "directive_id", "strategy"),
        "source_sheet": table,
        "engine_version": _pick(row, "engine_version", "engine_abi"),
        "pair_or_symbol": _pair_or_symbol(row),
        "test_start": _pick(row, "test_start", "start_date"),
        "test_end": _pick(row, "test_end", "end_date", "completed_at_utc"),
        "net_pct": _pick(row, "canonical_net_pct", "realized_net_pct"),
        "net_profit_usd": _pick(row, "canonical_final_equity_usd", "total_net_profit",
                                "final_realized_usd", "net_profit"),
        "ret_dd": _pick(row, "canonical_ret_dd", "return_dd_ratio"),
        "max_dd_pct": _pick(row, "canonical_max_dd_pct", "max_dd_pct", "max_drawdown_pct"),
        "profit_factor": row.get("profit_factor"),
        "trades": _pick(row, "trades_total", "total_trades", "trade_count"),
        "cycles": row.get("cycles_completed"),
        "supersede_reason": row.get("supersede_reason"),
        "superseded_by": row.get("superseded_by"),
        "backtests_path": row.get("backtests_path"),
        "retired_at_utc": _utc_now(),
    }


# ── Cold archive (read-concat-write parquet, deduped by run_id) ──────────────

def _load_archive_ids() -> set[str]:
    p = _retired_parquet()
    if not p.is_file():
        return set()
    import pandas as pd

    # A corrupt/unreadable EXISTING archive is a HARD error — raise, never swallow.
    # Swallowing would blind the dedup AND let _append_archive overwrite prior
    # retirement history (whose ledger rows are already gone — irrecoverable).
    df = pd.read_parquet(p, columns=["run_id"])
    return {str(x) for x in df["run_id"].tolist()}


def _append_archive(records: list[dict]) -> int:
    """Append records to the cold parquet (create if absent). Returns count
    written. Caller is responsible for dedupe (already-archived filtering)."""
    if not records:
        return 0
    import pandas as pd

    p = _retired_parquet()
    p.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(records)
    if p.is_file():
        # Read raises on a corrupt archive — let it propagate (fail-fast). NEVER
        # fall back to overwriting the file with only `new` (would destroy the
        # prior retired-run history; those rows' ledger entries are already gone).
        old = pd.read_parquet(p)
        combined = pd.concat([old, new], ignore_index=True)
    else:
        combined = new
    combined.to_parquet(p, index=False)
    return len(records)


# ── Drop (authorized, guarded) ──────────────────────────────────────────────

def _backup_ledger() -> Path:
    db = _ledger_db()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    bak = db.with_name(f"ledger.db.bak_{stamp}")
    shutil.copy2(db, bak)
    return bak


def _drop_row(conn: sqlite3.Connection, table: str, run_id: str) -> int:
    """Scoped, guarded DELETE. Returns rows deleted (must be 0 or 1)."""
    cur = conn.execute(
        f'DELETE FROM "{table}" WHERE run_id = ? '
        "AND (is_current = 0 OR is_current = '0' OR is_current = 0.0)",
        (run_id,),
    )
    return cur.rowcount


# ── Prune artifacts (move to quarantine, recoverable) ────────────────────────

def _capsule_dir(row: dict) -> Path | None:
    """Resolve the run's backtests capsule dir from its row.

    - cointegration / basket: prefer the stored ``backtests_path`` (relative →
      state root). ``basket_sheet`` stores ``.../<capsule>/raw/`` — strip a
      trailing ``raw`` so we move the WHOLE capsule, not just its raw/ subdir.
    - master_filter (single-asset): ``strategy`` is ALREADY symbol-suffixed (the
      full capsule id), so the capsule is ``backtests/<strategy>`` — never
      ``<strategy>_<symbol>`` (that double-suffix collides with composite capsules).
    - basket with a NULL ``backtests_path``: derive ``backtests/<directive_id>_<basket_id>``.
    """
    btp = (row.get("backtests_path") or "").strip()
    if btp:
        bp = Path(btp)
        if not bp.is_absolute():
            bp = _state_root() / btp
        if bp.name == "raw":            # basket_sheet '.../<capsule>/raw/' → parent is the capsule
            bp = bp.parent
        return bp
    strat = row.get("strategy")
    if strat:                            # master_filter: strategy IS the full capsule id
        return _backtests_dir() / str(strat)
    did, bid = row.get("directive_id"), row.get("basket_id")
    if did and bid:                      # basket_sheet, NULL backtests_path
        return _backtests_dir() / f"{did}_{bid}"
    if did:
        return _backtests_dir() / str(did)
    return None


def _move_to_quarantine(src: Path, kind: str) -> str | None:
    """Move ``src`` under quarantine/retired/<kind>/. No-op if absent."""
    try:
        if not src.exists():
            return None
    except OSError:
        return None
    dest_root = _quarantine_dir() / kind
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / src.name
    if dest.exists():
        # Already quarantined a same-named dir — suffix to avoid clobber.
        dest = dest_root / f"{src.name}__{datetime.now(timezone.utc).strftime('%H%M%S')}"
    shutil.move(str(src), str(dest))
    return str(dest)


def _prune_artifacts(run_id: str, row: dict) -> list[str]:
    moved: list[str] = []
    run_home = _runs_dir() / run_id
    m = _move_to_quarantine(run_home, "runs")
    if m:
        moved.append(m)
    cap = _capsule_dir(row)
    if cap is not None:
        m = _move_to_quarantine(cap, "backtests")
        if m:
            moved.append(m)
    return moved


# ── Audit ────────────────────────────────────────────────────────────────────

def _audit(entry: dict) -> None:
    p = _audit_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": _utc_now(), **entry}) + "\n")


# ── Public API ───────────────────────────────────────────────────────────────

def retire(run_ids: list[str], *, execute: bool = False, force: bool = False) -> dict:
    """Retire the given superseded runs. Dry-run unless ``execute=True``.

    Returns a summary dict: ``{retired, skipped, refused, errors}`` lists.
    """
    summary = {"retired": [], "skipped": [], "refused": [], "errors": [], "dry_run": not execute}
    run_ids = list(dict.fromkeys(s.strip() for s in run_ids if s and s.strip()))
    db = _ledger_db()
    if not db.exists():
        summary["errors"].append(f"ledger.db not found at {db}")
        return summary

    archived_ids = _load_archive_ids()
    pending_archive: list[dict] = []
    backed_up = False

    conn = sqlite3.connect(str(db))
    try:
        for run_id in run_ids:
            run_id = run_id.strip()
            if not run_id:
                continue
            table, row = _find_run_row(conn, run_id)
            if row is None:
                summary["skipped"].append({"run_id": run_id, "why": "not in any ledger sheet"})
                continue
            # GUARD 1: must be explicitly superseded (is_current = 0).
            if not _is_superseded(row.get("is_current")):
                summary["refused"].append(
                    {"run_id": run_id, "table": table,
                     "why": f"is_current={row.get('is_current')!r} is not 0 (live row) — refused"}
                )
                continue
            # GUARD 2: a successor must exist, unless --force.
            if not _has_successor(row.get("superseded_by")) and not force:
                summary["refused"].append(
                    {"run_id": run_id, "table": table,
                     "why": "no superseded_by successor (use --force to retire anyway)"}
                )
                continue

            rec = _compact_record(table, row)
            cap = _capsule_dir(row)
            plan = {
                "run_id": run_id, "table": table,
                "archive": run_id not in archived_ids,
                "runs_dir": str(_runs_dir() / run_id),
                "capsule": str(cap) if cap else None,
            }

            if not execute:
                summary["retired"].append({**plan, "executed": False})
                continue

            # EXECUTE — archive BEFORE drop.
            if run_id not in archived_ids:
                pending_archive.append(rec)
                archived_ids.add(run_id)
            # Flush archive immediately so the row is in cold storage before drop.
            if pending_archive:
                _append_archive(pending_archive)
                pending_archive = []

            if not backed_up:
                bak = _backup_ledger()
                _audit({"action": "backup", "path": str(bak)})
                backed_up = True

            dropped = _drop_row(conn, table, run_id)
            if dropped != 1:
                conn.rollback()
                summary["errors"].append(
                    {"run_id": run_id, "table": table,
                     "why": f"DELETE affected {dropped} rows (expected 1) — rolled back, NOT pruned"}
                )
                continue
            conn.commit()
            # Record the committed drop BEFORE pruning, so a prune failure can't
            # lose the audit trail of an already-dropped (+ archived + backed-up) run.
            _audit({"action": "retire", "run_id": run_id, "table": table,
                    "archived": True, "dropped": True})
            try:
                moved = _prune_artifacts(run_id, row)
                _audit({"action": "pruned", "run_id": run_id, "moved": moved})
            except OSError as exc:  # prune is best-effort — a move failure must not abort the batch
                moved = []
                _audit({"action": "prune_failed", "run_id": run_id, "error": str(exc)})
                summary["errors"].append(
                    {"run_id": run_id, "table": table,
                     "why": f"dropped + archived OK but artifact prune failed: {exc}"}
                )
            summary["retired"].append({**plan, "executed": True, "moved": moved})
    finally:
        conn.close()

    return summary


def drift_check() -> dict:
    """Read-only: count superseded (is_current=0) runs that still have on-disk
    HEAVY artifacts (``runs/<id>/`` OR the ``backtests/`` capsule) and are NOT
    yet in the cold archive (= skipped retirements)."""
    out = {"unretired": [], "count": 0}
    db = _ledger_db()
    if not db.exists():
        return out
    archived = _load_archive_ids()
    runs_dir = _runs_dir()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        for table in _LEDGER_TABLES:
            cols = _table_columns(conn, table)
            if "run_id" not in cols or "is_current" not in cols:
                continue
            sel = ["run_id"] + [c for c in ("backtests_path", "strategy", "symbol") if c in cols]
            try:
                cur = conn.execute(
                    f'SELECT {", ".join(sel)} FROM "{table}" '
                    "WHERE is_current = 0 OR is_current = '0' OR is_current = 0.0"
                )
            except sqlite3.Error:
                continue
            for r in cur.fetchall():
                rid = str(r["run_id"])
                if rid in archived:
                    continue
                row = dict(r)
                has_runs = (runs_dir / rid).exists()
                cap = _capsule_dir(row)
                has_cap = bool(cap and cap.exists())
                if has_runs or has_cap:
                    out["unretired"].append({"run_id": rid, "table": table})
    finally:
        conn.close()
    out["count"] = len(out["unretired"])
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Retire superseded runs: archive row -> cold parquet, drop the "
                    "live ledger row (authorized), prune artifacts. Dry-run by default."
    )
    ap.add_argument("--run-ids", help="Comma-separated predecessor run_ids to retire.")
    ap.add_argument("--execute", action="store_true",
                    help="Actually mutate (archive + drop + prune). Default is dry-run.")
    ap.add_argument("--force", action="store_true",
                    help="Retire a superseded run even if it has no successor (superseded_by).")
    ap.add_argument("--drift-check", action="store_true",
                    help="Read-only: report superseded runs with un-pruned artifacts not yet archived.")
    ap.add_argument("--json", action="store_true", help="Emit JSON.")
    args = ap.parse_args(argv)

    if args.drift_check:
        result = drift_check()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"[drift-check] {result['count']} superseded run(s) with artifacts "
                  f"NOT yet retired (archived):")
            for u in result["unretired"][:50]:
                print(f"  - {u['run_id']}  ({u['table']})")
            if result["count"] > 50:
                print(f"  ... and {result['count'] - 50} more")
        return 0

    if not args.run_ids:
        ap.error("provide --run-ids or --drift-check")

    ids = [s for s in args.run_ids.split(",") if s.strip()]
    result = retire(ids, execute=args.execute, force=args.force)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        mode = "EXECUTE" if args.execute else "DRY-RUN (no changes written)"
        print(f"[retire] {mode}")
        print(f"  retired : {len(result['retired'])}")
        print(f"  skipped : {len(result['skipped'])}  (not in ledger)")
        print(f"  refused : {len(result['refused'])}  (live row / no successor)")
        print(f"  errors  : {len(result['errors'])}")
        for r in result["refused"]:
            print(f"    REFUSED {r['run_id']}: {r['why']}")
        for e in result["errors"]:
            print(f"    ERROR   {e}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
