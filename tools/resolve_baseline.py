"""resolve_baseline.py — unify a prior experiment's homes into one descriptor.

Given any handle to a prior experiment (a 24-hex ``run_id``, a strategy /
directive name, or a series tag), return — in one read-only call — the
authoritative ``is_current`` run plus its **code**, **seed (directive)**,
**baseline metrics**, and **provenance paths**, unified from ``strategies/`` +
``backtests/`` + ``runs/``.

The invariant this tool exists to enforce (RESOLVE_BASELINE_SPEC §3):

    Authoritative = is_current=1 (or IS NULL legacy), selected in SQL before
    any row is returned. The first-match path is never trusted.

``find_run_id_for_directive`` (``pipeline_utils.py:357``) returns the FIRST
match and ``read_master_filter`` applies no ``is_current`` filter, so a bare
name lookup can silently pick a superseded run. This resolver wraps the lookup
with ``query_master_filter_current`` (``is_current`` enforced in SQL) instead
of trusting first-match.

**Read-only, side-effect-free.** No ledger mutation, no folder creation, no
pipeline re-run, no backfill. Every degradation (old/missing artifact) is a
warning — the resolver never crashes on an old run, it returns best-available
and names the gap.

CLI::

    python tools/resolve_baseline.py <handle> [--symbol SYM] [--all-symbols] \
           [--require seed|metrics|code|all] [--json]

Default output is a compact human summary; ``--json`` emits the
``BaselineReference`` schema (RESOLVE_BASELINE_SPEC §6).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.state_paths import (  # noqa: E402
    BACKTESTS_DIR,
    RUNS_DIR,
    STRATEGIES_DIR,
    capsule_path,
    strategy_dir,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^[0-9a-f]{24}$")
# Per-symbol handle = <base>_<SYMBOL[+SYMBOL...]>; symbol token is 3-12 uppercase
# alnum (single FX/IDX symbol or concatenated basket symbols).
_SYMBOL_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<symbol>[A-Z0-9]{3,12})$")

# Exit codes (RESOLVE_BASELINE_SPEC §12)
EXIT_OK = 0
EXIT_NOT_RESOLVED = 1
EXIT_REQUIRE_UNMET = 2


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


@dataclass
class BaselineReference:
    """One unified descriptor of a resolved baseline (RESOLVE_BASELINE_SPEC §6).

    A single ``BaselineReference`` ties a handle to its authoritative run and
    that run's three governed homes (``strategy_dir`` / ``backtest_dir`` /
    ``run_dir``), plus the resolved seed, code, metrics, and reports. A bare
    multi-symbol directive handle yields N of these (one per symbol).
    """

    handle: str
    resolved: bool = False
    run_id: str | None = None
    strategy: str | None = None          # symbol-agnostic base id
    symbol: str | None = None
    run_type: str | None = None          # "basket" | "single_asset"
    is_current: bool | None = None

    homes: dict[str, str | None] = field(default_factory=dict)
    code: dict[str, Any] = field(default_factory=dict)
    seed: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    reports: dict[str, str | None] = field(default_factory=dict)

    siblings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Series-tag cohort flag (RESOLVE_BASELINE_SPEC §13.2)
    is_cohort: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (paths already stringified at build time)."""
        return dataclasses.asdict(self)


@dataclass
class BaselineResult:
    """Top-level resolver result: one or more references plus the handle."""

    handle: str
    references: list[BaselineReference] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """True iff at least one reference resolved to an authoritative run."""
        return any(r.resolved for r in self.references)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "resolved": self.resolved,
            "references": [r.to_dict() for r in self.references],
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResolveError(Exception):
    """Raised for hard-error conditions that map to a non-zero exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_NOT_RESOLVED):
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Handle classification
# ---------------------------------------------------------------------------


def _classify_handle(handle: str) -> str:
    """Classify a handle as ``run_id`` | ``name`` | ``series``.

    - ``run_id``: 24 lowercase hex chars.
    - ``name``:   anything that looks like a strategy / directive id (starts
      with the numeric namespace prefix ``NN_``).
    - ``series``: a bare cohort / series tag (e.g. ``GP_ZCRS_CXN1_Z25``) — no
      namespace prefix; resolved against the cohort view (§13.2).
    """
    h = handle.strip()
    if _RUN_ID_RE.match(h):
        return "run_id"
    if re.match(r"^\d{2}_", h):
        return "name"
    return "series"


def _split_symbol(strategy_col: str) -> tuple[str, str | None]:
    """Split a per-symbol strategy id into ``(base, symbol)``.

    The ledger ``strategy`` column already carries the symbol suffix
    (``01_MR_..._P02_EURUSD``); the symbol-agnostic ``base`` keys the
    ``strategies/`` home, the full id keys the ``backtests/`` capsule.
    Returns ``(strategy_col, None)`` if no recognizable symbol suffix.
    """
    m = _SYMBOL_SUFFIX_RE.match(strategy_col)
    if m:
        return m.group("base"), m.group("symbol")
    return strategy_col, None


# ---------------------------------------------------------------------------
# Ledger resolution (the spine, RESOLVE_BASELINE_SPEC §5.2)
# ---------------------------------------------------------------------------


def _load_master_filter():
    """Import the current-row ledger reader lazily (keeps import cheap)."""
    from tools.ledger_db import query_master_filter, query_master_filter_current

    return query_master_filter, query_master_filter_current


def _resolve_ledger_rows(handle: str, kind: str, symbol: str | None):
    """Return ``(rows_df, warnings)`` of authoritative master_filter rows.

    Applies the ``is_current`` SQL filter, then handles supersession
    follow-through and multi-symbol expansion. ``rows_df`` may be empty
    (caller decides ``resolved:false`` vs error).
    """
    import pandas as pd

    query_master_filter, query_master_filter_current = _load_master_filter()
    warnings: list[str] = []

    if kind == "run_id":
        cur = query_master_filter_current(run_id=handle)
        if not cur.empty:
            return cur, warnings
        # Maybe the run exists but is superseded → follow to the successor.
        allrows = query_master_filter()
        row = allrows[allrows["run_id"].astype(str) == handle]
        if not row.empty:
            succ, w = _follow_superseded(row, query_master_filter_current)
            warnings += w
            if succ is not None and not succ.empty:
                return succ, warnings
        return cur, warnings  # empty

    # kind == "name": try exact strategy match, then base-prefix (multi-symbol).
    cur = query_master_filter_current(strategy=handle)
    if cur.empty:
        # base handle → all per-symbol rows whose base == handle
        allcur = query_master_filter_current()
        if not allcur.empty and "strategy" in allcur.columns:
            bases = allcur["strategy"].astype(str).map(lambda s: _split_symbol(s)[0])
            cur = allcur[bases == handle].copy()

    if cur.empty:
        # Nothing current — maybe fully superseded; follow to live successor.
        allrows = query_master_filter()
        sub = allrows[allrows["strategy"].astype(str) == handle]
        if sub.empty and not allrows.empty:
            bases = allrows["strategy"].astype(str).map(lambda s: _split_symbol(s)[0])
            sub = allrows[bases == handle]
        if not sub.empty:
            succ, w = _follow_superseded(sub, query_master_filter_current)
            warnings += w
            if succ is not None and not succ.empty:
                cur = succ

    if cur.empty:
        return cur, warnings

    # Narrow by symbol if requested.
    if symbol is not None:
        cur = cur[cur["symbol"].astype(str) == symbol].copy()
        if cur.empty:
            warnings.append(
                f"no is_current row for symbol={symbol!r}; available symbols not matched"
            )

    # Append-only violation guard: >1 is_current for the same (base, symbol).
    if not cur.empty:
        cur = cur.copy()
        cur["_base"] = cur["strategy"].astype(str).map(lambda s: _split_symbol(s)[0])
        dup = cur.groupby(["_base", "symbol"]).size()
        offenders = dup[dup > 1]
        if len(offenders):
            pairs = ", ".join(f"{b}/{s}" for (b, s) in offenders.index)
            rids = ", ".join(cur["run_id"].astype(str).tolist())
            raise ResolveError(
                "append-only violation: >1 is_current row for "
                f"({pairs}) — run_ids: [{rids}]",
                exit_code=EXIT_REQUIRE_UNMET,
            )
        cur = cur.drop(columns=["_base"])

    return cur, warnings


def _follow_superseded(rows, query_master_filter_current):
    """Follow ``superseded_by`` from superseded rows to the live successor.

    Returns ``(successor_rows_df_or_None, warnings)``. Walks at most a few hops
    to avoid a corrupt cycle looping forever.
    """
    import pandas as pd

    warnings: list[str] = []
    if "superseded_by" not in rows.columns:
        return None, warnings
    targets = (
        rows["superseded_by"].dropna().astype(str).map(str.strip)
    )
    targets = [t for t in targets if t and t.lower() != "none"]
    seen: set[str] = set()
    for rid in targets:
        hop = rid
        for _ in range(6):
            if hop in seen:
                break
            seen.add(hop)
            succ = query_master_filter_current(run_id=hop)
            if not succ.empty:
                warnings.append(
                    f"all matching rows superseded; followed superseded_by → {hop}"
                )
                return succ, warnings
            # successor itself superseded → chase its successor
            query_master_filter, _ = _load_master_filter()
            allrows = query_master_filter()
            nxt = allrows[allrows["run_id"].astype(str) == hop]
            if nxt.empty or "superseded_by" not in nxt.columns:
                break
            val = str(nxt.iloc[0].get("superseded_by") or "").strip()
            if not val or val.lower() == "none":
                break
            hop = val
    return None, warnings


# ---------------------------------------------------------------------------
# Run-type detection (RESOLVE_BASELINE_SPEC §9)
# ---------------------------------------------------------------------------


def _detect_run_type(run_id: str | None, backtest_dir: Path) -> str:
    """Return ``"basket"`` or ``"single_asset"``.

    A run is a basket iff it appears in ``basket_sheet`` OR its capsule holds
    the per-bar parquet / RECYCLE_RULE_SOURCE.py artifacts. Defaults to
    ``single_asset`` (the dominant population).
    """
    if run_id:
        try:
            from tools.ledger_db import query_baskets

            bdf = query_baskets(current_only=False)
            if not bdf.empty and (bdf["run_id"].astype(str) == run_id).any():
                return "basket"
        except Exception:
            pass
    if (backtest_dir / "raw" / "results_basket_per_bar.parquet").is_file():
        return "basket"
    if (backtest_dir / "RECYCLE_RULE_SOURCE.py").is_file():
        return "basket"
    return "single_asset"


# ---------------------------------------------------------------------------
# Seed (directive) resolution ladder (RESOLVE_BASELINE_SPEC §7)
# ---------------------------------------------------------------------------


def _resolve_seed(
    base: str,
    full_strategy: str,
    symbol: str | None,
    sdir: Path,
    bdir: Path,
    rdir: Path,
) -> dict[str, Any]:
    """Walk the seed ladder; stop at the first hit. Records source + truth.

    Returns a dict with ``path`` (str|None), ``source``, ``truth``, and
    ``stake_usd`` (parsed ``basket.initial_stake_usd`` if present, else None).
    """
    candidates: list[tuple[Path, str, str]] = [
        (bdir / "DIRECTIVE_SOURCE.txt", "DIRECTIVE_SOURCE", "exact_execution"),
        (rdir / "directive.txt", "run_directive_txt", "exact_execution"),
        (sdir / "directive.txt", "strategy_directive_txt", "human_keyed_continuity"),
    ]
    # Tier 4: completed/ corpus fallback (keyed by directive id; try full then base).
    completed_dir = _REPO_ROOT / "backtest_directives" / "completed"
    for did in (full_strategy, base):
        candidates.append(
            (completed_dir / f"{did}.txt", "completed", "human_keyed_continuity")
        )

    for path, source, truth in candidates:
        try:
            if path.is_file():
                stake = _parse_stake(path)
                return {
                    "path": str(path),
                    "source": source,
                    "truth": truth,
                    "stake_usd": stake,
                }
        except OSError:
            continue

    # Tier 5: git recovery (live paths, then any path).
    git_content, git_source = _recover_seed_via_git(full_strategy, base)
    if git_content is not None:
        return {
            "path": None,
            "source": git_source,
            "truth": "human_keyed_continuity",
            "stake_usd": _parse_stake_from_text(git_content),
            "content": git_content,
        }

    # ABSENT
    return {"path": None, "source": "ABSENT", "truth": None, "stake_usd": None}


def _recover_seed_via_git(full_strategy: str, base: str) -> tuple[str | None, str]:
    """Best-effort git directive recovery (ladder tier 5). Never raises."""
    for did in (full_strategy, base):
        try:
            from tools.recover_admitted_directive import recover_directive

            rec = recover_directive(did)
            if rec and rec.get("content"):
                return rec["content"], "git"
        except Exception:
            pass
        try:
            from tools.backfill_run_directives import recover_anypath_git

            content = recover_anypath_git(did)
            if content:
                return content, "git"
        except Exception:
            pass
    return None, "git"


def _parse_stake(path: Path) -> float | None:
    """Parse ``basket.initial_stake_usd`` from a directive file, or None."""
    try:
        from tools.pipeline_utils import parse_directive

        data = parse_directive(path)
        basket = data.get("basket")
        if isinstance(basket, dict) and "initial_stake_usd" in basket:
            return float(basket["initial_stake_usd"])
        # parse_directive hoists test: sub-keys to root, so a flat key may exist.
        if "initial_stake_usd" in data:
            return float(data["initial_stake_usd"])
    except Exception:
        # Fall back to a lenient text scan rather than failing the whole resolve.
        try:
            return _parse_stake_from_text(path.read_text(encoding="utf-8"))
        except OSError:
            return None
    return None


def _parse_stake_from_text(text: str) -> float | None:
    """Lenient regex scan for ``initial_stake_usd: <number>`` in raw text."""
    m = re.search(r"initial_stake_usd\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Code resolution (RESOLVE_BASELINE_SPEC §8)
# ---------------------------------------------------------------------------


def _resolve_code(run_type: str, sdir: Path, bdir: Path, full_strategy: str) -> dict[str, Any]:
    """Resolve the executable artifact path + source. Never raises.

    single_asset → ``strategy_dir/strategy.py`` → git → ABSENT.
    basket       → ``backtest_dir/RECYCLE_RULE_SOURCE.py`` → git → ABSENT.

    ``strategy.py.bak`` is ignored. ABSENT is reported, never assumed present.
    """
    if run_type == "basket":
        rule_src = bdir / "RECYCLE_RULE_SOURCE.py"
        if rule_src.is_file():
            return {"path": str(rule_src), "source": "capsule"}
    else:
        strat_py = sdir / "strategy.py"
        if strat_py.is_file():
            return {"path": str(strat_py), "source": "strategies_dir"}

    # git fallback (best-effort; we only confirm a blob is reachable, never write).
    git_path = _code_in_git(full_strategy)
    if git_path is not None:
        return {"path": git_path, "source": "git"}

    return {"path": None, "source": "ABSENT"}


def _code_in_git(full_strategy: str) -> str | None:
    """Best-effort: locate a committed strategy.py blob path for the id.

    Returns a ``git:<sha>:<path>`` reference string if found, else None.
    Read-only — never checks out or writes.
    """
    import subprocess

    base, _ = _split_symbol(full_strategy)
    for did in (full_strategy, base):
        try:
            p = subprocess.run(
                [
                    "git", "log", "--all", "-n1", "--format=%H", "--",
                    f":(glob)strategies/{did}/strategy.py",
                ],
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            sha = (p.stdout or "").strip().splitlines()
            if sha:
                return f"git:{sha[0]}:strategies/{did}/strategy.py"
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Metric resolution (RESOLVE_BASELINE_SPEC §9)
# ---------------------------------------------------------------------------


def _resolve_metrics(
    run_type: str, bdir: Path, stake_usd: float | None, warnings: list[str]
) -> dict[str, Any]:
    """Resolve baseline metrics per run-type. Never raises; degrades to ABSENT."""
    if run_type == "basket":
        return _basket_metrics(bdir, stake_usd, warnings)
    return _single_asset_metrics(bdir, warnings)


def _basket_metrics(
    bdir: Path, stake_usd: float | None, warnings: list[str]
) -> dict[str, Any]:
    """Recompute basket metrics via ``canonical_metrics`` (the sole truth).

    Never reads ``canonical_net_pct`` / ``final_realized_usd÷stake`` from MPS —
    those denominators diverge (real case 33.5% vs 655%). The parquet
    ``equity_total_usd`` via ``canonical_metrics()`` is authoritative.
    """
    parquet = bdir / "raw" / "results_basket_per_bar.parquet"
    if not parquet.is_file():
        warnings.append(
            "basket parquet absent (results_basket_per_bar.parquet); "
            "metrics unavailable (legacy V2 REPORT parse not implemented)"
        )
        return {"source": "ABSENT"}
    if stake_usd is None:
        warnings.append(
            "stake_usd unresolved from seed; basket metrics use 1000.0 fallback "
            "denominator (net_pct/max_dd_pct may be off)"
        )
        stake = 1000.0
    else:
        stake = stake_usd
    try:
        from tools.basket_hypothesis.canonical_metrics import canonical_metrics

        cm = canonical_metrics(parquet, stake)
        return {
            "source": "parquet_canonical",
            "net_pct": cm.get("net_pct"),
            "max_dd_pct": cm.get("max_dd_pct"),
            "ret_dd": cm.get("ret_dd"),
            "recycle_events": cm.get("events", {}).get("recycle_executed"),
            "cycles_completed": cm.get("cycles_completed"),
            "cycles_won": cm.get("cycles_won"),
            "exit_reason": cm.get("exit_reason"),
            "stake_usd": cm.get("stake_usd"),
        }
    except Exception as exc:  # noqa: BLE001 — never crash on an old/odd parquet
        warnings.append(f"canonical_metrics failed: {exc!r}; metrics ABSENT")
        return {"source": "ABSENT"}


def _single_asset_metrics(bdir: Path, warnings: list[str]) -> dict[str, Any]:
    """Read the 7 single-asset metrics from named CSV columns; derive the rest.

    Sources (best-available):
      raw/results_standard.csv → trade_count, profit_factor, net_pnl_usd
      raw/results_risk.csv     → sharpe_ratio, max_drawdown_pct
      raw/results_tradelevel.csv → derive top5_concentration via compute_concentration
      raw/results_yearwise.csv → losing_years (count net_pnl_usd < 0)
    """
    import pandas as pd

    raw = bdir / "raw"
    out: dict[str, Any] = {"source": "csv_stage1"}
    any_hit = False

    std = raw / "results_standard.csv"
    if std.is_file():
        try:
            d = pd.read_csv(std)
            if len(d):
                r = d.iloc[0]
                out["trade_count"] = _num(r.get("trade_count"))
                out["profit_factor"] = _num(r.get("profit_factor"))
                out["net_pnl_usd"] = _num(r.get("net_pnl_usd"))
                any_hit = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"results_standard.csv unreadable: {exc!r}")
    else:
        warnings.append("results_standard.csv absent")

    risk = raw / "results_risk.csv"
    if risk.is_file():
        try:
            d = pd.read_csv(risk)
            if len(d):
                r = d.iloc[0]
                out["sharpe_ratio"] = _num(r.get("sharpe_ratio"))
                out["max_drawdown_pct"] = _num(r.get("max_drawdown_pct"))
                any_hit = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"results_risk.csv unreadable: {exc!r}")
    else:
        warnings.append("results_risk.csv absent")

    # top5_concentration — derived from trade-level PnLs.
    tl = raw / "results_tradelevel.csv"
    if tl.is_file():
        try:
            d = pd.read_csv(tl)
            if "pnl_usd" in d.columns and len(d):
                pnls = pd.to_numeric(d["pnl_usd"], errors="coerce").dropna().tolist()
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]
                gross_profit = sum(wins)
                gross_loss = abs(sum(losses))
                from tools.metrics_core import compute_concentration

                conc = compute_concentration(wins, losses, gross_profit, gross_loss)
                out["top5_concentration"] = conc.get("top5_pct_gross_profit")
                out["worst5_loss_pct"] = conc.get("worst5_loss_pct")
                any_hit = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"results_tradelevel.csv concentration derive failed: {exc!r}")
    else:
        warnings.append("results_tradelevel.csv absent; top5_concentration derived=missing")

    # losing_years — count years with negative net PnL.
    yw = raw / "results_yearwise.csv"
    if yw.is_file():
        try:
            d = pd.read_csv(yw)
            if "net_pnl_usd" in d.columns:
                vals = pd.to_numeric(d["net_pnl_usd"], errors="coerce")
                out["losing_years"] = int((vals < 0).sum())
                any_hit = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"results_yearwise.csv unreadable: {exc!r}")
    else:
        warnings.append("results_yearwise.csv absent; losing_years=missing")

    if not any_hit:
        out["source"] = "ABSENT"
    return out


def _num(v: Any) -> float | None:
    """Coerce a cell to float, or None on NaN / non-numeric."""
    try:
        import math

        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Report path resolution
# ---------------------------------------------------------------------------


def _resolve_reports(run_type: str, bdir: Path, base: str) -> dict[str, str | None]:
    """Locate strategy_card / basket_report / report_md within the capsule."""
    reports: dict[str, str | None] = {
        "strategy_card": None,
        "basket_report": None,
        "report_md": None,
    }
    card = bdir / "STRATEGY_CARD.md"
    if card.is_file():
        reports["strategy_card"] = str(card)
    # REPORT_*.md and BASKET_REPORT_*.md (named after the base directive id).
    try:
        if bdir.is_dir():
            for p in bdir.iterdir():
                name = p.name
                if name.startswith("BASKET_REPORT_") and name.endswith(".md"):
                    reports["basket_report"] = str(p)
                elif name.startswith("REPORT_") and name.endswith(".md"):
                    reports["report_md"] = str(p)
    except OSError:
        pass
    return reports


# ---------------------------------------------------------------------------
# Reference assembly
# ---------------------------------------------------------------------------


def _build_reference(
    handle: str,
    row,
    siblings: list[str],
    warnings: list[str],
) -> BaselineReference:
    """Assemble one ``BaselineReference`` from a single authoritative ledger row."""
    full_strategy = str(row["strategy"])
    symbol = str(row["symbol"]) if row.get("symbol") is not None else None
    run_id = str(row["run_id"])
    is_current_raw = row.get("is_current")
    # NULL / NaN is treated as current per schema default.
    is_current = True if is_current_raw is None or _is_nan(is_current_raw) else bool(
        int(float(is_current_raw))
    )

    base, _sym_from_strategy = _split_symbol(full_strategy)
    sym = symbol or _sym_from_strategy

    sdir = strategy_dir(base)
    # Capsule path: the ledger `strategy` column already carries the symbol
    # suffix, so the on-disk capsule IS backtests/<full_strategy>. Build via the
    # centralized helper using (base, symbol) so the f-string lives in one place.
    bdir = capsule_path(base, sym) if sym else (BACKTESTS_DIR / full_strategy)
    rdir = RUNS_DIR / run_id

    ref = BaselineReference(
        handle=handle,
        resolved=True,
        run_id=run_id,
        strategy=base,
        symbol=sym,
        is_current=is_current,
        siblings=siblings,
        warnings=list(warnings),
    )

    run_type = _detect_run_type(run_id, bdir)
    ref.run_type = run_type

    ref.homes = {
        "strategy_dir": str(sdir) if sdir.is_dir() else None,
        "backtest_dir": str(bdir) if bdir.is_dir() else None,
        "run_dir": str(rdir) if rdir.is_dir() else None,
    }
    if ref.homes["strategy_dir"] is None:
        ref.warnings.append(
            f"strategy_dir absent (strategies/{base}); code/seed continuity degraded"
        )
    if ref.homes["backtest_dir"] is None:
        ref.warnings.append(
            f"backtest_dir absent (capsule pruned: {bdir.name}); metrics/seed degraded"
        )

    # Seed (§7), then code (§8), then metrics (§9 — needs stake from seed).
    ref.seed = _resolve_seed(base, full_strategy, sym, sdir, bdir, rdir)
    if ref.seed.get("source") == "ABSENT":
        ref.warnings.append("provenance_gap: seed unrecoverable (old/grandfathered run)")
    # Drop bulky inline content from the emitted schema (path is the contract).
    ref.seed.pop("content", None)

    ref.code = _resolve_code(run_type, sdir, bdir, full_strategy)
    if ref.code.get("source") == "ABSENT":
        ref.warnings.append("provenance_gap: code unrecoverable (strategies/ ABSENT, no git blob)")

    ref.metrics = _resolve_metrics(run_type, bdir, ref.seed.get("stake_usd"), ref.warnings)

    ref.reports = _resolve_reports(run_type, bdir, base)
    return ref


def _is_nan(v: Any) -> bool:
    try:
        import math

        return isinstance(v, float) and math.isnan(v)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Series-tag (cohort) resolution (RESOLVE_BASELINE_SPEC §13.2)
# ---------------------------------------------------------------------------


def _resolve_series(handle: str) -> BaselineResult:
    """Resolve a bare series / cohort tag to a single representative reference.

    Picks the top-``ret_dd`` member of the cohort (basket_sheet rows whose
    directive_id contains the tag), flags ``is_cohort=true``, and points to
    ``compare_cohorts.py``. Does NOT return the full cohort (that is
    compare_cohorts' job).
    """
    result = BaselineResult(handle=handle)
    try:
        from tools.ledger_db import query_baskets

        bdf = query_baskets(current_only=True)
    except Exception as exc:  # noqa: BLE001
        ref = BaselineReference(handle=handle, resolved=False)
        ref.warnings.append(f"series resolution failed (basket view): {exc!r}")
        result.references.append(ref)
        return result

    if bdf.empty or "directive_id" not in bdf.columns:
        ref = BaselineReference(handle=handle, resolved=False)
        ref.warnings.append("no basket cohort rows available for series tag")
        result.references.append(ref)
        return result

    mask = bdf["directive_id"].astype(str).str.contains(re.escape(handle), na=False)
    cohort = bdf[mask]
    if cohort.empty:
        ref = BaselineReference(handle=handle, resolved=False)
        ref.warnings.append(f"series tag {handle!r} matched no cohort member")
        result.references.append(ref)
        return result

    rank_col = "canonical_ret_dd" if "canonical_ret_dd" in cohort.columns else None
    if rank_col:
        import pandas as pd

        cohort = cohort.assign(
            _r=pd.to_numeric(cohort[rank_col], errors="coerce")
        ).sort_values("_r", ascending=False, na_position="last")
    rep = cohort.iloc[0]
    rep_handle = str(rep["run_id"])

    # Resolve the representative by its run_id through the normal spine.
    rep_result = resolve_baseline(rep_handle)
    if rep_result.references:
        ref = rep_result.references[0]
    else:
        ref = BaselineReference(handle=handle, resolved=False)
    ref.handle = handle
    ref.is_cohort = True
    ref.note = (
        f"series tag → representative (top ret_dd) of {len(cohort)} cohort members; "
        f"use compare_cohorts.py for matched-pairs analysis"
    )
    result.references.append(ref)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_baseline(
    handle: str,
    *,
    symbol: str | None = None,
    require: str = "none",
) -> BaselineResult:
    """Resolve a handle to its authoritative baseline reference(s).

    Args:
        handle:  a 24-hex ``run_id``, a strategy / directive name, or a
            series / cohort tag.
        symbol:  disambiguate a multi-symbol directive to a single reference.
        require: gate strictness — ``"none"`` (best-available, default),
            ``"seed"``, ``"metrics"``, ``"code"``, or ``"all"``. A reference
            that cannot satisfy ``require`` is marked ``resolved=False``.

    Returns:
        ``BaselineResult`` whose ``.references`` holds one reference (run_id /
        ``--symbol`` / single-symbol directive) or N (bare multi-symbol
        directive). Never raises on old/missing artifacts — degradations land
        in each reference's ``warnings``. May raise ``ResolveError`` only for
        hard structural faults (append-only violation).
    """
    handle = handle.strip()
    kind = _classify_handle(handle)

    if kind == "series":
        result = _resolve_series(handle)
        _apply_require(result, require)
        return result

    rows, warnings = _resolve_ledger_rows(handle, kind, symbol)
    result = BaselineResult(handle=handle)

    if rows is None or rows.empty:
        ref = BaselineReference(handle=handle, resolved=False)
        ref.warnings = list(warnings) + [
            "no authoritative (is_current) ledger row found for handle"
        ]
        result.references.append(ref)
        return result

    # Sibling set: all symbols sharing this base directive.
    all_symbols = sorted(
        {str(s) for s in rows["symbol"].tolist() if s is not None}
    )

    for _, row in rows.iterrows():
        this_symbol = str(row["symbol"]) if row.get("symbol") is not None else None
        siblings = [s for s in all_symbols if s != this_symbol]
        ref = _build_reference(handle, row, siblings, warnings)
        result.references.append(ref)

    _apply_require(result, require)
    return result


def _apply_require(result: BaselineResult, require: str) -> None:
    """Mark references unresolved if the ``--require`` gate is unmet."""
    if require in (None, "none"):
        return
    needed = {
        "seed": ["seed"],
        "code": ["code"],
        "metrics": ["metrics"],
        "all": ["seed", "code", "metrics"],
    }.get(require, [])
    for ref in result.references:
        if not ref.resolved:
            continue
        for facet in needed:
            block = getattr(ref, facet, {}) or {}
            if block.get("source") in (None, "ABSENT"):
                ref.resolved = False
                ref.warnings.append(
                    f"--require {require}: {facet} unmet (source={block.get('source')})"
                )
                break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _compact_summary(result: BaselineResult) -> str:
    """Human-readable one-block-per-reference summary."""
    lines: list[str] = []
    n = len(result.references)
    lines.append(f"handle: {result.handle}   resolved: {result.resolved}   references: {n}")
    for i, ref in enumerate(result.references, 1):
        lines.append("-" * 72)
        prefix = f"[{i}/{n}] " if n > 1 else ""
        if not ref.resolved:
            lines.append(f"{prefix}UNRESOLVED")
            for w in ref.warnings:
                lines.append(f"    ! {w}")
            continue
        lines.append(
            f"{prefix}{ref.strategy}  symbol={ref.symbol}  type={ref.run_type}  "
            f"is_current={ref.is_current}"
        )
        lines.append(f"    run_id : {ref.run_id}")
        lines.append(f"    strat  : {ref.homes.get('strategy_dir')}")
        lines.append(f"    capsule: {ref.homes.get('backtest_dir')}")
        lines.append(f"    run    : {ref.homes.get('run_dir')}")
        lines.append(
            f"    seed   : {ref.seed.get('source')} ({ref.seed.get('truth')})"
        )
        lines.append(f"    code   : {ref.code.get('source')}")
        m = ref.metrics or {}
        msrc = m.get("source")
        if msrc == "parquet_canonical":
            lines.append(
                f"    metrics: net%={m.get('net_pct')}  dd%={m.get('max_dd_pct')}  "
                f"ret/dd={m.get('ret_dd')}  cycles={m.get('cycles_completed')}"
            )
        elif msrc == "csv_stage1":
            lines.append(
                f"    metrics: pf={m.get('profit_factor')}  net=${m.get('net_pnl_usd')}  "
                f"trades={m.get('trade_count')}  losing_yrs={m.get('losing_years')}  "
                f"top5={m.get('top5_concentration')}"
            )
        else:
            lines.append(f"    metrics: {msrc}")
        if ref.siblings:
            lines.append(f"    siblings: {', '.join(ref.siblings)}")
        if ref.is_cohort and ref.note:
            lines.append(f"    note   : {ref.note}")
        for w in ref.warnings:
            lines.append(f"    ! {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint (RESOLVE_BASELINE_SPEC §4)."""
    ap = argparse.ArgumentParser(
        description="Resolve a handle to its authoritative baseline reference(s).",
    )
    ap.add_argument("handle", help="run_id | strategy/directive name | series tag")
    ap.add_argument("--symbol", default=None, help="disambiguate a multi-symbol directive")
    ap.add_argument(
        "--all-symbols",
        action="store_true",
        help="return every symbol of a multi-symbol directive (default behavior; explicit flag)",
    )
    ap.add_argument(
        "--require",
        choices=["none", "seed", "metrics", "code", "all"],
        default="none",
        help="fail (exit!=0) if the named facet is unrecoverable",
    )
    ap.add_argument("--json", action="store_true", help="emit BaselineReference JSON")
    args = ap.parse_args(argv)

    # --symbol and --all-symbols are mutually exclusive in intent; --symbol wins.
    symbol = None if args.all_symbols else args.symbol

    try:
        result = resolve_baseline(args.handle, symbol=symbol, require=args.require)
    except ResolveError as exc:
        payload = {"handle": args.handle, "resolved": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_compact_summary(result))

    if not result.resolved:
        return EXIT_NOT_RESOLVED
    # require-unmet references downgrade resolved→False; if any reference is
    # unresolved due to an unmet require gate, signal exit 2.
    if args.require != "none" and not all(r.resolved for r in result.references):
        return EXIT_REQUIRE_UNMET
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
