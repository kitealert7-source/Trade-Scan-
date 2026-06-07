"""refresh_cointegration.py -- identity-preserving refresh of ONE cointegration
directive (cointegration pilot, 2026-06-07).

Re-runs an existing COINTREV directive IN PLACE: same directive_id (NO __E###
variant), a NEW run_id + full provenance receipt, a new cointegration_sheet row,
and the prior row marked is_current=0 by the writer (ledger_db.upsert_
cointegration_row's refresh-supersede). Scope: cointegration_sheet ONLY --
master_filter, mark_superseded, quarantine, and the platform-wide rerun
architecture are untouched. cointegration_sheet is not an AGENT.md append-only
ledger, so this changes writer behaviour, not a governance invariant.

    python tools/refresh_cointegration.py <directive_id> \
        --category {ENGINE|DATA_FRESH|PARAMETER|BUG_FIX} \
        --reason "<why>" [--window-mode current|recorded] [--dry-run]

--window-mode (default: current) -- explicit so a refresh never silently changes
two variables (engine AND window) at once:
  current  : re-derive the pair's CURRENT cointegrated span from the screener and
             set the directive window to it. Window-match-safe by construction;
             the deployment-grade artifact (DATA_FRESH + promotion). Used by the
             CADJPY/USDCHF promotion refresh.
  recorded : keep the directive's recorded start/end dates unchanged -- an
             apples-to-apples single-variable comparison (e.g. ENGINE/BUG_FIX:
             new engine, SAME window). window_validity_gate remains the arbiter:
             if the recorded window has fallen outside the current span the run
             is rejected there (correctly).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
INBOX_DIR = DIRECTIVES_ROOT / "INBOX"
_SEARCH_DIRS = (
    INBOX_DIR,
    DIRECTIVES_ROOT / "active_backup",
    DIRECTIVES_ROOT / "active",
    DIRECTIVES_ROOT / "completed",
    DIRECTIVES_ROOT / "archive",
)
CATEGORIES = ("ENGINE", "DATA_FRESH", "PARAMETER", "BUG_FIX")
WINDOW_MODES = ("current", "recorded")
_SCREEN_TF = "1d"            # cointegration BASIS tf (the screener span basis)
_METHODOLOGY = "v2_log_eg"
_N_CONFIRM = 5


def _resolve_directive(directive_id: str) -> Path:
    for d in _SEARCH_DIRS:
        p = d / f"{directive_id}.txt"
        if p.is_file() and p.stat().st_size > 0:
            return p
    raise FileNotFoundError(
        f"No directive '{directive_id}.txt' in {[d.name for d in _SEARCH_DIRS]}")


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"directive {path} is not a YAML mapping")
    return data


def _is_cointegration(data: dict) -> bool:
    return bool((data.get("basket") or {}).get("cointegration_join"))


def _current_span(pair_a: str, pair_b: str, lookback_days: int) -> tuple[str, str]:
    """(entry_date, exit_date) of the pair's CURRENT OPEN cointegrated span from
    the screener. Raises if the pair is not currently in a tradeable span."""
    import sqlite3

    from tools.cointegration_db import SQLITE_DB
    from tools.generate_cointrev_v3_directives import (
        _read_series, spans_confirmation_safe,
    )
    conn = sqlite3.connect(str(SQLITE_DB))
    series = []
    try:
        for pa, pb in ((pair_a, pair_b), (pair_b, pair_a)):
            series = _read_series(conn, pa, pb, _SCREEN_TF, lookback_days, _METHODOLOGY)
            if series:
                break
    finally:
        conn.close()
    if not series:
        raise ValueError(
            f"no screener history for {pair_a}/{pair_b} (tf={_SCREEN_TF}, "
            f"lookback={lookback_days}, {_METHODOLOGY})")
    spans = spans_confirmation_safe(series, N=_N_CONFIRM)
    if not spans:
        raise ValueError(
            f"{pair_a}/{pair_b} has no qualifying span (N={_N_CONFIRM})")
    entry_date, exit_date, _ = spans[-1]          # last enumerated == open span
    latest_as_of = series[-1][0]
    if exit_date != latest_as_of:
        raise ValueError(
            f"{pair_a}/{pair_b} is NOT in a current open span (last span ends "
            f"{exit_date}; latest as_of {latest_as_of}). The pair is not currently "
            f"in a tradeable cointegrated span -- use --window-mode=recorded, or "
            f"wait for re-cointegration.")
    return entry_date, exit_date


def _prior_run_id(directive_id: str) -> str | None:
    try:
        from tools.ledger_db import _connect
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT run_id FROM cointegration_sheet "
                "WHERE directive_id = ? AND is_current = 1 LIMIT 1",
                (directive_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _build_refresh_directive(data, directive_id, category, reason, window_mode,
                             prior_run_id):
    """Mutated directive dict: window per mode + refresh-authorization fields.
    Identity-preserving: test.name / test.strategy / the directive_id are NOT
    changed (the window is the evaluation, not the identity)."""
    data = dict(data)
    test = dict(data.get("test") or {})
    basket = data.get("basket") or {}
    symbols = data.get("symbols") or []

    if window_mode == "current":
        lookback = int((basket.get("cointegration_join") or {}).get("lookback_days", 252))
        entry, exit_ = _current_span(symbols[0], symbols[1], lookback)
        test["start_date"] = entry
        test["end_date"] = exit_
    # window_mode == "recorded": leave start_date / end_date untouched.

    # --- TEMPORARY REUSE of the existing rerun authorization path -------------
    # repeat_override_reason was DESIGNED for the Idea-Gate REPEAT_FAILED bypass.
    # We reuse it here ONLY to authorize the in-place refresh past admission; it
    # is NOT "the cointegration refresh architecture." A dedicated refresh-intent
    # signal is the eventual replacement (debt logged in COINTEGRATION_REFRESH_
    # IMPLEMENTATION_PLAN_2026-06-07.md). The uniqueness guard is handled
    # separately + explicitly via `run_pipeline --refresh` (a typed param), not
    # through this field -- keep these two seams distinct.
    override = (f"[COINT-REFRESH:{category}@{date.today().isoformat()} "
                f"mode={window_mode} directive={directive_id}] {reason.strip()}")
    if len(override.strip()) < 50:
        override += " [identity-preserving cointegration refresh; temporary rerun-auth reuse]"
    test["repeat_override_reason"] = override
    if prior_run_id:
        test["rerun_of"] = prior_run_id

    data["test"] = test
    return data


def cmd_refresh(args) -> int:
    try:
        src = _resolve_directive(args.directive_id)
    except FileNotFoundError as e:
        print(f"[ABORT] {e}")
        return 1
    data = _load(src)
    if not _is_cointegration(data):
        print(f"[ABORT] {args.directive_id} is not a cointegration directive "
              f"(no basket.cointegration_join). refresh_cointegration is "
              f"cointegration-only by design.")
        return 1
    if len(data.get("symbols") or []) != 2:
        print(f"[ABORT] expected a 2-symbol cointegration directive; got "
              f"{data.get('symbols')}")
        return 1

    prior = _prior_run_id(args.directive_id)
    before = data.get("test") or {}
    try:
        out = _build_refresh_directive(
            data, args.directive_id, args.category, args.reason,
            args.window_mode, prior)
    except ValueError as e:
        print(f"[ABORT] window resolution failed: {e}")
        return 1
    after = out["test"]

    print(f"  directive : {args.directive_id}")
    print(f"  category  : {args.category}   window-mode: {args.window_mode}")
    if args.window_mode == "recorded":
        print(f"  window    : {after.get('start_date')} -> {after.get('end_date')}  (recorded, unchanged)")
    else:
        print(f"  window    : {after.get('start_date')} -> {after.get('end_date')}  "
              f"(was {before.get('start_date')} -> {before.get('end_date')})")
    print(f"  prior run : {prior or '(none found)'}")
    print(f"  override  : {after['repeat_override_reason'][:100]}...")

    if args.dry_run:
        print("[DRY RUN] nothing written; pipeline not invoked.")
        return 0

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest = INBOX_DIR / f"{args.directive_id}.txt"
    dest.write_text(
        yaml.safe_dump(out, sort_keys=False, default_flow_style=False,
                       allow_unicode=True, width=120),
        encoding="utf-8")
    print(f"[OK] staged refreshed directive -> {dest.relative_to(PROJECT_ROOT)}")
    print(f"[RUN] python tools/run_pipeline.py {args.directive_id} --refresh")
    rc = subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "tools" / "run_pipeline.py"),
         args.directive_id, "--refresh"],
        cwd=str(PROJECT_ROOT))
    if rc != 0:
        print(f"[WARN] pipeline exit {rc}; prior cointegration_sheet row unchanged "
              f"(the writer supersedes the prior row ONLY on a successful new append).")
        return rc
    print(f"[DONE] refresh complete. New run is_current=1; prior row "
          f"({prior or 'n/a'}) is now is_current=0.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("directive_id")
    p.add_argument("--category", required=True, choices=CATEGORIES)
    p.add_argument("--reason", required=True, help="human reason (>=20 chars)")
    p.add_argument("--window-mode", default="current", choices=WINDOW_MODES,
                   help="current (default): re-derive the pair's current span; "
                        "recorded: keep the directive's recorded window.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if len(args.reason.strip()) < 20:
        print("[ABORT] --reason must be >=20 chars of genuine content.")
        return 1
    return cmd_refresh(args)


if __name__ == "__main__":
    raise SystemExit(main())
