"""
Preflight Idea Evaluation — Concept Reuse Gate v1.

Non-blocking gate that checks whether a directive's concept was already tested
and/or failed in prior research. Uses three data sources:

  1. run_summary.csv — pre-joined run stats: PF, trades, PnL, portfolio verdict,
     candidate status, run status (complete/failed/invalid). 697+ rows, one read.
  2. hypothesis_log.json — structured hypothesis test results with ACCEPT/REJECT
     decisions and rejection reasons.
  3. RESEARCH_MEMORY.md / RESEARCH_MEMORY_ARCHIVE.md — qualitative findings
     with failure tags and exhausted-concept markers.

Fallback: Strategy_Master_Filter.xlsx (if run_summary.csv doesn't exist yet).

Returns a structured evaluation dict on success. Never raises (non-blocking).
With --strict-preflight: REPEAT_FAILED status causes exit(1).

Integration: called by admission_controller.py BEFORE namespace/sweep gates.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import parse_directive
from config.state_paths import MASTER_FILTER_PATH, STATE_ROOT, REGISTRY_DIR
from config.asset_classification import (
    classify_asset,
    infer_asset_class_from_symbols,
    parse_strategy_name,
    MixedAssetClassError,
    UnknownSymbolError,
)

# Data source paths
RUN_SUMMARY_PATH = STATE_ROOT / "research" / "run_summary.csv"
HYPOTHESIS_LOG_PATH = STATE_ROOT / "hypothesis_log.json"

# Reuse the authoritative naming pattern from namespace_gate
NAME_PATTERN = re.compile(
    r"^(?:C_)?"
    r"(?P<idea_id>\d{2})_"
    r"(?P<family>[A-Z0-9]+)_"
    r"(?P<symbol>[A-Z0-9]+)_"
    r"(?P<timeframe>[A-Z0-9]+)_"
    r"(?P<model>[A-Z0-9]+)"
    r"(?:_(?P<filter>[A-Z0-9]+))?_"
    r"S(?P<sweep>\d{2})_"
    r"V(?P<variant>\d+)_"
    r"P(?P<parent>\d{2})"
    r"(?:__[A-Z0-9]+)?$"
)

# Strategy type inference from family token
_STRATEGY_TYPE_MAP: dict[str, str] = {
    "MR": "mean_reversion",
    "REV": "mean_reversion",
    "CONT": "continuation",
    "TREND": "trend",
    "BRK": "breakout",
    "PA": "price_action",
    "STR": "structural",
}

# Tags in RESEARCH_MEMORY that indicate a failed concept
_FAILURE_TAGS = frozenset({
    "failed_concept", "idea_exhausted", "exhausted", "failed",
    "no_edge", "negative", "structurally_invalid",
})

# PF thresholds for classification
_PF_FAILED = 1.10
_PF_WEAK = 1.20


# ---------------------------------------------------------------------------
# Core gate function
# ---------------------------------------------------------------------------

def evaluate_idea(directive_path: str | Path) -> dict[str, Any]:
    """Evaluate whether a directive's concept was previously tested.

    Returns a structured dict — never raises, never blocks.
    """
    directive_path = Path(directive_path)
    if not directive_path.exists():
        return _result("NEW", "LOW", 0, "Directive file not found — cannot evaluate.",
                       [], "PROCEED")

    # --- Parse directive and extract concept signature ---
    try:
        config = parse_directive(directive_path)
    except Exception as e:
        return _result("NEW", "LOW", 0, f"Directive parse error: {e}", [], "PROCEED")

    strategy_name = config.get("strategy") or config.get("name") or directive_path.stem
    m = NAME_PATTERN.match(strategy_name)
    if not m:
        return _result("NEW", "LOW", 0,
                       f"Strategy name '{strategy_name}' does not match naming pattern.",
                       [], "PROCEED")

    model = m.group("model")
    timeframe = m.group("timeframe")
    family = m.group("family")
    idea_id = m.group("idea_id")
    strategy_type = _STRATEGY_TYPE_MAP.get(family, "unknown")

    # --- Determine directive asset class (MODEL + ASSET_CLASS filter) ---
    # PORT family is exempt — portfolio strategies intentionally span classes.
    asset_class: str | None = None
    if family != "PORT":
        symbols_list = config.get("symbols") or []
        try:
            asset_class = infer_asset_class_from_symbols([str(s) for s in symbols_list])
        except (MixedAssetClassError, UnknownSymbolError, ValueError):
            # Gate is non-blocking on internal errors; single-asset enforcement
            # is the admission controller's job. Fall back to symbol-token-based
            # class from the strategy name.
            asset_class = classify_asset(strategy_name)

    # --- Determine directive signal_version (Phase 2 gate key extension) ---
    # User-declared integer identifying the signal-primitive generation.
    # Missing / legacy directives default to 1. The gate filters prior runs
    # by this field so that e.g. CHOCH_V3 (sv=3) is not blocked by legacy
    # CHOCH_V1/V2 (sv=1) failures. The column is additive - if a data source
    # lacks it, rows are treated as sv=1.
    try:
        signal_version = int(config.get("signal_version") or 1)
    except (TypeError, ValueError):
        signal_version = 1

    # --- Step 1: Search all data sources (filtered by asset_class + signal_version) ---
    # Primary: run_summary.csv (pre-joined: PF, trades, verdict, status — one CSV read)
    summary_matches = _search_run_summary(model, timeframe, asset_class, signal_version)

    # Supplementary: hypothesis_log.json (structured ACCEPT/REJECT decisions)
    hyp_matches = _search_hypothesis_log(model, idea_id, asset_class, signal_version)

    # Qualitative: RESEARCH_MEMORY (failure tags, exhausted concepts)
    # Note: concept-level entries without Strategy: line remain global (by design).
    rm_matches = _search_research_memory(model, timeframe, idea_id, asset_class, signal_version)

    # Fallback: Master Filter (only if run_summary.csv absent)
    mf_matches: list[dict[str, Any]] = []
    if not summary_matches:
        mf_matches = _search_master_filter(model, timeframe, asset_class, signal_version)

    total_matches = len(summary_matches) + len(hyp_matches) + len(rm_matches) + len(mf_matches)

    if total_matches == 0:
        ac_note = f" ASSET_CLASS={asset_class}" if asset_class else ""
        return _result("NEW", "HIGH", 0,
                       f"No prior runs found for MODEL={model} TF={timeframe}{ac_note}. Novel concept.",
                       [], "PROCEED")

    # --- Step 2: Build examples and aggregate metrics ---
    examples: list[dict[str, Any]] = []
    pf_values: list[float] = []
    trade_counts: list[int] = []

    # run_summary.csv: group by strategy_id (may have per-symbol rows)
    failed_run_count = 0
    complete_run_count = 0
    seen_strategies: set[str] = set()

    if summary_matches:
        from collections import defaultdict
        _by_strat: dict[str, list[dict]] = defaultdict(list)
        for row in summary_matches:
            _by_strat[row.get("strategy_id", "?")].append(row)
            status = row.get("status", "")
            if status in ("failed", "invalid", "no_trades", "quarantined"):
                failed_run_count += 1
            elif status == "complete":
                complete_run_count += 1

        for sid, rows in _by_strat.items():
            seen_strategies.add(sid)
            pfs = [r["avg_profit_factor"] for r in rows if r.get("avg_profit_factor")]
            trades = int(sum(r.get("total_trades", 0) for r in rows))
            avg_pf = sum(pfs) / len(pfs) if pfs else 0.0
            symbols = sorted(set(str(r.get("symbols", "?")) for r in rows))
            verdicts = set(str(r.get("portfolio_verdict", "")) for r in rows) - {"", "nan"}
            cand_status = set(str(r.get("candidate_status", "")) for r in rows) - {"", "nan"}
            run_statuses = set(str(r.get("status", "")) for r in rows)

            pf_values.append(avg_pf)
            trade_counts.append(trades)
            examples.append({
                "strategy": sid,
                "profit_factor": round(avg_pf, 3),
                "total_trades": trades,
                "symbols": ",".join(symbols),
                "verdict": ",".join(verdicts) if verdicts else "",
                "candidate_status": ",".join(cand_status) if cand_status else "",
                "run_status": ",".join(run_statuses),
                "source": "run_summary",
            })

    # Master Filter fallback
    for row in mf_matches:
        sid = str(row.get("strategy", "?"))
        if sid in seen_strategies:
            continue
        seen_strategies.add(sid)
        pf = row.get("profit_factor", 0.0)
        trades = row.get("total_trades", 0)
        pf_values.append(pf)
        trade_counts.append(trades)
        examples.append({
            "strategy": sid,
            "profit_factor": round(pf, 3),
            "total_trades": trades,
            "source": "Master_Filter",
        })

    # Hypothesis log entries
    hyp_rejected = 0
    hyp_accepted = 0
    for entry in hyp_matches:
        decision = entry.get("decision", "")
        if decision == "REJECT":
            hyp_rejected += 1
        elif decision == "ACCEPT":
            hyp_accepted += 1

    if hyp_matches:
        examples.append({
            "source": "hypothesis_log",
            "total_hypotheses": len(hyp_matches),
            "accepted": hyp_accepted,
            "rejected": hyp_rejected,
            "summary": (f"{len(hyp_matches)} hypotheses tested: "
                        f"{hyp_accepted} accepted, {hyp_rejected} rejected"),
        })
        # Top 3 individual hypothesis entries for context
        for entry in hyp_matches[:3]:
            examples.append({
                "source": "hypothesis_log_detail",
                "strategy": entry.get("strategy", "?"),
                "hypothesis": entry.get("hypothesis", "?"),
                "decision": entry.get("decision", "?"),
                "pf": entry.get("pf"),
                "rejection_reason": entry.get("rejection_reason", ""),
            })

    # RESEARCH_MEMORY findings
    for entry in rm_matches:
        examples.append({
            "strategy": entry.get("strategy", "?"),
            "tags": entry.get("tags", ""),
            "finding": entry.get("finding", ""),
            "source": "RESEARCH_MEMORY",
        })

    # Check for explicit failure tags in research memory
    has_failure_tag = any(
        any(t in _FAILURE_TAGS for t in e.get("tags", "").replace(" ", "").split(","))
        for e in rm_matches
    )

    has_exhausted_mention = any(
        "exhausted" in e.get("finding", "").lower()
        or "exhausted" in e.get("tags", "").lower()
        for e in rm_matches
    )

    # --- Step 3: Classify ---
    status, confidence, recommendation, summary = _classify(
        model, timeframe, pf_values, trade_counts,
        has_failure_tag, has_exhausted_mention, rm_matches,
        failed_run_count=failed_run_count,
        complete_run_count=complete_run_count,
        hyp_rejected=hyp_rejected,
        hyp_accepted=hyp_accepted,
    )

    # --- Step 4: Generate suggestions for WARN/FAIL cases ---
    suggestions: list[str] = []
    if recommendation in ("RECONSIDER", "PROCEED_WITH_CAUTION"):
        suggestions = _generate_suggestions(
            model, timeframe, family, strategy_type,
            summary_matches, hyp_matches, rm_matches, pf_values,
            has_exhausted_mention,
        )

    # --- Step 5: Build memory basis (audit trail — log only, never enforces) ---
    memory_basis: list[dict[str, Any]] = []
    if summary_matches:
        memory_basis.append({"source": "run_summary", "entries_used": len(summary_matches)})
    if hyp_matches:
        memory_basis.append({"source": "hypothesis_log", "entries_used": len(hyp_matches)})
    if rm_matches:
        rm_basis: dict[str, Any] = {"source": "RESEARCH_MEMORY", "entries_used": len(rm_matches)}
        if _rm_parse_warnings > 0:
            rm_basis["parse_warnings"] = _rm_parse_warnings
        memory_basis.append(rm_basis)
    if mf_matches:
        memory_basis.append({"source": "Master_Filter", "entries_used": len(mf_matches)})

    # Cap examples at 8
    top_examples = examples[:8]

    return _result(status, confidence, total_matches, summary,
                   top_examples, recommendation, suggestions, memory_basis)


# ---------------------------------------------------------------------------
# Data source 1: run_summary.csv (pre-joined — primary)
# ---------------------------------------------------------------------------

def _row_asset_class(row: dict[str, Any], strategy_id: str) -> str:
    """Derive asset class for a run_summary row.

    Uses symbols column first; falls back to the SYMBOL token in strategy_id.
    Returns "FX" on any failure (safe default — aligns with legacy behavior).
    """
    symbols_field = str(row.get("symbols", "") or "").strip()
    if symbols_field and symbols_field.lower() != "nan":
        syms = [s.strip() for s in symbols_field.split(",") if s.strip()]
        if syms:
            try:
                return infer_asset_class_from_symbols(syms, strict_unknown=False)
            except (MixedAssetClassError, ValueError):
                pass
    return classify_asset(strategy_id)


def _row_signal_version(row: Any) -> int:
    """Read signal_version from a run_summary row. Missing/blank -> 1 (legacy).

    Accepts pandas Series or plain dict.
    """
    val = row.get("signal_version") if hasattr(row, "get") else None
    if val is None:
        return 1
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return 1
    except Exception:
        pass
    try:
        return int(val)
    except (TypeError, ValueError):
        return 1


def _search_run_summary(
    model: str, timeframe: str, asset_class: str | None = None,
    signal_version: int | None = None,
) -> list[dict[str, Any]]:
    """Find rows in run_summary.csv whose strategy_id matches MODEL token.

    If asset_class is provided, additionally filter to rows whose derived
    asset class matches (MODEL + ASSET_CLASS gate).

    If signal_version is provided, rows whose signal_version differs are
    excluded (legacy rows without the column are treated as sv=1).

    run_summary.csv columns: run_id, strategy_id, status, tier, symbol_count,
    symbols, timeframe, total_trades, net_pnl_usd, avg_profit_factor,
    avg_win_rate, max_drawdown_pct, portfolio_verdict, portfolio_pf,
    portfolio_sharpe, candidate_status, in_portfolio, risk_profile,
    signal_version (Phase 2, additive).
    """
    if not RUN_SUMMARY_PATH.exists():
        return []
    try:
        import pandas as pd
        df = pd.read_csv(RUN_SUMMARY_PATH, dtype={"run_id": str})
    except Exception:
        return []

    matches: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sid = str(row.get("strategy_id", ""))
        m = NAME_PATTERN.match(sid)
        if not m:
            continue
        if m.group("model") != model:
            continue
        if asset_class is not None:
            row_ac = _row_asset_class(row, sid)
            if row_ac != asset_class:
                continue
        if signal_version is not None:
            if _row_signal_version(row) != signal_version:
                continue
        matches.append({
                "run_id": str(row.get("run_id", "")),
                "strategy_id": sid,
                "status": str(row.get("status", "")),
                "tier": str(row.get("tier", "")),
                "timeframe": str(row.get("timeframe", "")),
                "total_trades": _safe_float(row.get("total_trades")),
                "net_pnl_usd": _safe_float(row.get("net_pnl_usd")),
                "avg_profit_factor": _safe_float(row.get("avg_profit_factor")),
                "avg_win_rate": _safe_float(row.get("avg_win_rate")),
                "max_drawdown_pct": _safe_float(row.get("max_drawdown_pct")),
                "portfolio_verdict": str(row.get("portfolio_verdict", "")),
                "candidate_status": str(row.get("candidate_status", "")),
                "symbols": str(row.get("symbols", "")),
                "tf_match": str(row.get("timeframe", "")).lower() == timeframe.lower(),
            })
    return matches


# ---------------------------------------------------------------------------
# Data source 2: hypothesis_log.json (structured hypothesis test results)
# ---------------------------------------------------------------------------

def _search_hypothesis_log(
    model: str, idea_id: str, asset_class: str | None = None,
    signal_version: int | None = None,
) -> list[dict[str, Any]]:
    """Find hypothesis test entries for matching MODEL/idea in hypothesis_log.json.

    If asset_class is provided, filter entries whose strategy's inferred asset
    class matches. If signal_version is provided, entries whose
    'signal_version' field differs are excluded (missing -> 1).

    Each entry has: strategy, hypothesis, decision (ACCEPT/REJECT/SKIP),
    baseline_metrics, pass_metrics, rejection_reason.
    """
    if not HYPOTHESIS_LOG_PATH.exists():
        return []
    try:
        with open(HYPOTHESIS_LOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    matches: list[dict[str, Any]] = []
    for entry in data:
        strategy = str(entry.get("strategy", ""))
        m = NAME_PATTERN.match(strategy)
        if not m:
            continue
        if m.group("model") != model and m.group("idea_id") != idea_id:
            continue
        if asset_class is not None:
            if classify_asset(strategy) != asset_class:
                continue
        if signal_version is not None:
            entry_sv_raw = entry.get("signal_version", 1)
            try:
                entry_sv = int(entry_sv_raw) if entry_sv_raw is not None else 1
            except (TypeError, ValueError):
                entry_sv = 1
            if entry_sv != signal_version:
                continue
        result = entry.get("result") or entry.get("pass_metrics") or {}
        matches.append({
            "strategy": strategy,
            "hypothesis": str(entry.get("hypothesis", "")),
            "decision": str(entry.get("decision", entry.get("stage", ""))),
            "pf": result.get("pf") or result.get("profit_factor"),
            "rejection_reason": str(entry.get("rejection_reason", "") or ""),
            "timestamp": str(entry.get("timestamp", "")),
        })
    return matches


# ---------------------------------------------------------------------------
# Data source 3: RESEARCH_MEMORY.md + Archive
# ---------------------------------------------------------------------------

def _load_research_entries_from_index() -> tuple[list[dict], int] | None:
    """Try to load entries from the pre-built JSON index.

    Returns (entries, parse_warnings) or None if index is unavailable/stale.
    """
    try:
        from tools.generate_research_memory_index import INDEX_PATH
    except ImportError:
        return None

    if not INDEX_PATH.exists():
        return None

    try:
        import json as _json
        data = _json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entries" not in data:
            return None
        return data["entries"], data.get("parse_warnings", 0)
    except Exception:
        return None


def _entry_asset_class(strategy_field: str) -> str | None:
    """Infer asset class from a RESEARCH_MEMORY entry's Strategy: field.

    Returns None when no parseable strategy name is present — such entries
    are concept-level and remain global (intentional bias, see plan §3).
    """
    if not strategy_field:
        return None
    parsed = parse_strategy_name(strategy_field)
    if parsed:
        return parsed["asset_class"]
    return None


def _search_research_memory(
    model: str, timeframe: str, idea_id: str,
    asset_class: str | None = None,
    signal_version: int | None = None,
) -> list[dict[str, Any]]:
    """Scan RESEARCH_MEMORY for entries mentioning the MODEL or idea family.

    If asset_class is provided, filter entries whose Strategy: field resolves
    to a different asset class. Entries without a parseable Strategy: field
    remain global (concept-level, apply across asset classes).

    Reads from JSON index if available; falls back to parsing markdown.
    Propagates parse_warnings count via _rm_parse_warnings module-level variable.
    """
    global _rm_parse_warnings
    _rm_parse_warnings = 0
    results: list[dict[str, Any]] = []

    # --- Try JSON index first ---
    index_data = _load_research_entries_from_index()
    if index_data is not None:
        all_entries, parse_warnings = index_data
        _rm_parse_warnings = parse_warnings
        for entry in all_entries:
            strategy_field = entry.get("strategy", "")
            tags_field = entry.get("tags", "")

            model_in_strategy = model.upper() in strategy_field.upper()
            model_in_tags = model.upper() in tags_field.upper()
            family_match = f"_{idea_id}_" in strategy_field

            if model_in_strategy or model_in_tags or family_match:
                # Asset-class filter: skip entries whose parseable Strategy:
                # field resolves to a different asset class. Concept-level
                # entries (no parseable strategy) remain global.
                if asset_class is not None:
                    entry_ac = _entry_asset_class(strategy_field)
                    if entry_ac is not None and entry_ac != asset_class:
                        continue

                body = entry.get("body", "")
                finding = body[:200].replace("\n", " ").strip()
                if len(body) > 200:
                    finding += "..."

                results.append({
                    "strategy": strategy_field,
                    "tags": tags_field,
                    "finding": finding,
                    "tf_match": timeframe.lower() in tags_field.lower(),
                    "date": entry.get("date", ""),
                })
        return results

    # --- Fallback: parse markdown directly ---
    for filename in ("RESEARCH_MEMORY.md", "RESEARCH_MEMORY_ARCHIVE.md"):
        path = PROJECT_ROOT / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        entries, pw = _parse_research_entries(text)
        _rm_parse_warnings += pw
        for entry in entries:
            strategy_field = entry.get("strategy", "")
            tags_field = entry.get("tags", "")

            model_in_strategy = model.upper() in strategy_field.upper()
            model_in_tags = model.upper() in tags_field.upper()
            family_match = f"_{idea_id}_" in strategy_field

            if model_in_strategy or model_in_tags or family_match:
                # Asset-class filter: skip entries whose parseable Strategy:
                # field resolves to a different asset class. Concept-level
                # entries (no parseable strategy) remain global.
                if asset_class is not None:
                    entry_ac = _entry_asset_class(strategy_field)
                    if entry_ac is not None and entry_ac != asset_class:
                        continue

                body = entry.get("body", "")
                finding = body[:200].replace("\n", " ").strip()
                if len(body) > 200:
                    finding += "..."

                results.append({
                    "strategy": strategy_field,
                    "tags": tags_field,
                    "finding": finding,
                    "tf_match": timeframe.lower() in tags_field.lower(),
                    "date": entry.get("date", ""),
                })

    return results


# Module-level variable to propagate parse warnings to memory_basis
_rm_parse_warnings: int = 0


def _parse_research_entries(text: str) -> tuple[list[dict[str, str]], int]:
    """Parse RESEARCH_MEMORY entries into structured dicts with fail-fast detection.

    Returns (entries, parse_warnings_count).
    Malformed entries are logged with line numbers but NOT silently skipped.
    """
    try:
        from tools.generate_research_memory_index import parse_research_memory
        entries_raw, warnings = parse_research_memory(text, "inline")
        if warnings:
            for w in warnings:
                print(f"  [RESEARCH_MEMORY PARSE WARNING] {w}")
        # Map to the legacy dict shape expected by callers
        entries = []
        for e in entries_raw:
            entries.append({
                "date": e.get("date", ""),
                "tags": e.get("tags", ""),
                "strategy": e.get("strategy", ""),
                "body": e.get("body", ""),
            })
        return entries, len(warnings)
    except Exception as exc:
        print(f"  [WARN] Fail-fast parser unavailable ({exc}), using legacy parser")
        return _parse_research_entries_legacy(text), 0


def _parse_research_entries_legacy(text: str) -> list[dict[str, str]]:
    """Legacy regex parser — fallback only."""
    entries: list[dict[str, str]] = []
    blocks = re.split(r"\n---\s*\n", text)

    for block in blocks:
        block = re.sub(r"^---\s*\n", "", block).strip()
        if not block:
            continue

        header_match = re.match(
            r"^(\d{4}-\d{2}-\d{2})\s*\|\s*Tags:\s*([^|]+?)"
            r"(?:\s*\|\s*Strategy:\s*(.+?))?"
            r"(?:\s*\|\s*Run IDs?:\s*(.+?))?$",
            block.split("\n")[0],
        )
        alt_header = re.match(
            r"^###\s+Entry:\s+Family\s+(\d+)\s+.*?(?:\u2014|--)\s*(.*)",
            block.split("\n")[0],
        )

        if header_match:
            entries.append({
                "date": header_match.group(1),
                "tags": header_match.group(2).strip(),
                "strategy": (header_match.group(3) or "").strip(),
                "body": "\n".join(block.split("\n")[1:]).strip(),
            })
        elif alt_header:
            idea_id = alt_header.group(1)
            tags_m = re.search(r"Tags:\s*(.+)", block)
            strat_m = re.search(r"Strateg(?:y|ies):\s*(.+)", block)
            date_m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", block)
            body_lines = [
                line for line in block.split("\n")
                if not line.startswith(("###", "Tags:", "Date:", "Strateg"))
            ]
            entries.append({
                "date": date_m.group(1) if date_m else "",
                "tags": tags_m.group(1).strip() if tags_m else "",
                "strategy": strat_m.group(1).strip() if strat_m else f"Family_{idea_id}",
                "body": "\n".join(body_lines).strip(),
            })

    return entries


# ---------------------------------------------------------------------------
# Fallback: Strategy_Master_Filter.xlsx
# ---------------------------------------------------------------------------

def _search_master_filter(
    model: str,
    timeframe: str,
    asset_class: str | None = None,
    signal_version: int | None = None,
) -> list[dict[str, Any]]:
    """Fallback: only used if run_summary.csv doesn't exist.

    If signal_version is provided, rows without a matching signal_version
    column (or with a differing value) are excluded. Legacy rows without
    the column are treated as sv=1.
    """
    try:
        from tools.ledger_db import read_master_filter
        df = read_master_filter()
    except Exception:
        return []
    if df.empty:
        return []

    matches: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sid = str(row.get("strategy", ""))
        m = NAME_PATTERN.match(sid)
        if not m:
            continue
        if m.group("model") == model:
            if asset_class is not None:
                row_ac = _row_asset_class(row, sid)
                if row_ac != asset_class:
                    continue
            if signal_version is not None:
                if _row_signal_version(row) != signal_version:
                    continue
            matches.append({
                "strategy": sid,
                "profit_factor": _safe_float(row.get("profit_factor")),
                "total_trades": _safe_int(row.get("total_trades")),
                "timeframe": str(row.get("timeframe", "")),
                "source": "Master_Filter",
            })
    return matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float:
    """Coerce to float, return 0.0 on failure."""
    try:
        v = float(val)
        return 0.0 if v != v else v  # NaN check
    except (TypeError, ValueError):
        return 0.0


def _safe_int(val: Any) -> int:
    """Coerce to int, return 0 on failure."""
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(
    model: str,
    timeframe: str,
    pf_values: list[float],
    trade_counts: list[int],
    has_failure_tag: bool,
    has_exhausted_mention: bool,
    rm_matches: list[dict],
    *,
    failed_run_count: int = 0,
    complete_run_count: int = 0,
    hyp_rejected: int = 0,
    hyp_accepted: int = 0,
) -> tuple[str, str, str, str]:
    """Return (status, confidence, recommendation, summary)."""

    # --- RESEARCH_MEMORY override: exhausted/failure tags override quantitative PF ---
    # This is the "memory override" — if prior research explicitly concluded the
    # concept is dead, PF data from individual sweeps does not rehabilitate it.
    if has_exhausted_mention:
        pf_note = ""
        if pf_values:
            avg = sum(pf_values) / len(pf_values)
            pf_note = f" (Note: avg PF={avg:.2f} from {len(pf_values)} strategies, " \
                      f"but research concluded concept is exhausted.)"
        return (
            "REPEAT_FAILED", "HIGH", "RECONSIDER",
            f"MODEL={model} on TF={timeframe} was explicitly marked as EXHAUSTED "
            f"in RESEARCH_MEMORY. Prior research concluded this concept lacks viable edge."
            f"{pf_note}"
        )

    if has_failure_tag:
        pf_note = ""
        if pf_values:
            avg = sum(pf_values) / len(pf_values)
            pf_note = f" (avg PF={avg:.2f} from {len(pf_values)} strategies — " \
                      f"but RESEARCH_MEMORY has failure tags.)"
        return (
            "REPEAT_FAILED", "HIGH", "RECONSIDER",
            f"MODEL={model} has failure tags in RESEARCH_MEMORY "
            f"(failed_concept/no_edge/idea_exhausted).{pf_note}"
        )

    # Registry-only signal: many failed runs with no successful completions
    if failed_run_count >= 3 and complete_run_count == 0 and not pf_values:
        return (
            "REPEAT_FAILED", "HIGH", "RECONSIDER",
            f"MODEL={model}: {failed_run_count} failed/no_trades runs, "
            f"0 completions. Concept attempted multiple times without success."
        )

    # If we have PF data, classify by metrics
    if pf_values:
        avg_pf = sum(pf_values) / len(pf_values)
        max_pf = max(pf_values)
        total_trades = sum(trade_counts)

        failure_note = ""
        if failed_run_count > 0:
            failure_note = f" Registry: {failed_run_count} failed runs."
        hyp_note = ""
        if hyp_rejected > 0:
            hyp_note = f" Hypotheses: {hyp_accepted} accepted, {hyp_rejected} rejected."

        if avg_pf <= _PF_FAILED:
            confidence = "HIGH" if len(pf_values) >= 3 else "MEDIUM"
            return (
                "REPEAT_FAILED", confidence, "RECONSIDER",
                f"MODEL={model} TF={timeframe}: avg PF={avg_pf:.2f}, "
                f"max PF={max_pf:.2f} across {len(pf_values)} strategies."
                f"{failure_note}{hyp_note} All prior attempts below profitability threshold."
            )

        if avg_pf <= _PF_WEAK:
            return (
                "REPEAT_WEAK", "MEDIUM", "PROCEED_WITH_CAUTION",
                f"MODEL={model} TF={timeframe}: avg PF={avg_pf:.2f}, "
                f"max PF={max_pf:.2f} across {len(pf_values)} strategies."
                f"{failure_note}{hyp_note} Edge exists but is thin/unstable. "
                f"Ensure this pass adds a structural change."
            )

        # PF > 1.20 — concept has demonstrated edge
        return (
            "REPEAT_PROMISING", "HIGH", "PROCEED",
            f"MODEL={model} TF={timeframe}: avg PF={avg_pf:.2f}, "
            f"max PF={max_pf:.2f} across {len(pf_values)} strategies, "
            f"{total_trades} total trades.{failure_note}{hyp_note} "
            f"Concept has demonstrated viable edge."
        )

    # Only qualitative matches, no PF metrics (failure tags already handled above)
    reg_note = ""
    if complete_run_count or failed_run_count:
        reg_note = f" Runs: {complete_run_count} complete, {failed_run_count} failed."
    return (
        "REPEAT_PROMISING", "LOW", "PROCEED_WITH_CAUTION",
        f"MODEL={model} found in RESEARCH_MEMORY ({len(rm_matches)} entries) "
        f"but no quantitative data.{reg_note} Prior research exists — review context."
    )


# ---------------------------------------------------------------------------
# Suggestion generator — actionable hypothesis changes for WARN/FAIL cases
# ---------------------------------------------------------------------------

# Dimensions that can be structurally changed to differentiate a new attempt
_STRUCTURAL_DIMENSIONS = [
    "timeframe", "regime_filter", "exit_design", "entry_trigger",
    "risk_model", "session_filter", "volatility_filter", "trend_filter",
]

# All timeframes in the system (for "try a different TF" suggestions)
_ALL_TIMEFRAMES = {"5M", "15M", "30M", "1H", "4H", "1D"}


def _suggestion(text: str, stype: str, confidence: str) -> dict[str, str]:
    """Build a typed suggestion dict. Advisory only — never controls gate logic."""
    return {"text": text, "type": stype, "confidence": confidence}


def _suggestion_confidence(
    match_count: int, has_memory_evidence: bool,
) -> str:
    """Derive suggestion confidence from evidence density."""
    if has_memory_evidence and match_count >= 5:
        return "HIGH"
    if match_count >= 3 or has_memory_evidence:
        return "MEDIUM"
    return "LOW"


def _generate_suggestions(
    model: str,
    timeframe: str,
    family: str,
    strategy_type: str,
    summary_matches: list[dict[str, Any]],
    hyp_matches: list[dict[str, Any]],
    rm_matches: list[dict[str, Any]],
    pf_values: list[float],
    has_exhausted_mention: bool,
) -> list[dict[str, str]]:
    """Generate max 3 typed suggestions. Advisory only — never gates execution.

    Each suggestion is {text, type, confidence} where:
      type:       EXPLOIT (build on known edge), EXPLORE (diverge from past),
                  AVOID (strong failure evidence)
      confidence: HIGH / MEDIUM / LOW — based on match count + memory evidence

    Returns at most 3 suggestions, priority-ranked: AVOID > EXPLOIT > EXPLORE.
    """
    candidates: list[dict[str, str]] = []
    has_rm = len(rm_matches) > 0
    n_matches = len(summary_matches) + len(hyp_matches) + len(rm_matches)
    base_conf = _suggestion_confidence(n_matches, has_rm)

    # --- AVOID: RESEARCH_MEMORY failure evidence ---
    for entry in rm_matches:
        body = entry.get("finding", "")
        tags = entry.get("tags", "")

        if "tail" in body.lower() or "tail" in tags.lower():
            candidates.append(_suggestion(
                "RESEARCH_MEMORY notes tail-dependent returns. "
                "New hypothesis must address concentration risk: "
                "cap max-win contribution or add anti-tail filters.",
                "AVOID", "HIGH",
            ))
        if "flat" in body.lower() or "no_edge" in tags.lower():
            candidates.append(_suggestion(
                "RESEARCH_MEMORY indicates flat/no-edge periods. "
                "Add a regime gate to disable during unfavorable conditions.",
                "AVOID", "HIGH",
            ))
        if "overfit" in body.lower():
            candidates.append(_suggestion(
                "RESEARCH_MEMORY warns about overfitting. "
                "Reduce parameter count or test on out-of-sample ranges.",
                "AVOID", "HIGH",
            ))

    if has_exhausted_mention:
        candidates.append(_suggestion(
            "Concept marked EXHAUSTED. Incremental parameter changes will not help. "
            "Requires fundamentally different entry logic, asset class, or "
            "combination with a complementary signal.",
            "AVOID", "HIGH",
        ))

    # --- AVOID: hypothesis log rejection patterns ---
    rejected_reasons: list[str] = []
    accepted_changes: list[str] = []
    for entry in hyp_matches:
        decision = entry.get("decision", "")
        reason = entry.get("rejection_reason", "")
        hypothesis = entry.get("hypothesis", "")
        if decision == "REJECT" and reason:
            rejected_reasons.append(reason)
        elif decision == "ACCEPT" and hypothesis:
            accepted_changes.append(hypothesis)

    if rejected_reasons:
        pf_rej = sum(1 for r in rejected_reasons if "PF" in r.upper() or "profit" in r.lower())
        retention_rej = sum(1 for r in rejected_reasons if "retention" in r.lower())
        conf = "HIGH" if len(rejected_reasons) >= 3 else base_conf

        if pf_rej > 0:
            candidates.append(_suggestion(
                f"PF degraded in {pf_rej} rejected passes. "
                f"Tighten entry conditions or add regime/volatility filter.",
                "AVOID", conf,
            ))
        if retention_rej > 0:
            candidates.append(_suggestion(
                f"Trade retention too low in {retention_rej} passes. "
                f"Soften thresholds or use composite filters instead of hard cutoffs.",
                "AVOID", conf,
            ))

    # --- EXPLOIT: build on known working edge ---
    if accepted_changes:
        candidates.append(_suggestion(
            f"Previously accepted: {'; '.join(accepted_changes[:2])}. "
            f"Build on these rather than reverting.",
            "EXPLOIT", base_conf,
        ))

    if pf_values and not has_exhausted_mention:
        avg_pf = sum(pf_values) / len(pf_values)
        max_pf = max(pf_values)
        if avg_pf <= _PF_FAILED and max_pf > _PF_FAILED:
            candidates.append(_suggestion(
                f"Avg PF={avg_pf:.2f} but best attempt PF={max_pf:.2f}. "
                f"Investigate best variant — narrow down rather than broadening.",
                "EXPLOIT", base_conf,
            ))
        elif _PF_FAILED < avg_pf <= _PF_WEAK:
            candidates.append(_suggestion(
                f"Thin edge (avg PF={avg_pf:.2f}). "
                f"Focus on exit optimization or quality filter to cut weakest setups.",
                "EXPLOIT", base_conf,
            ))

    # --- EXPLORE: diverge from past patterns ---
    tried_tfs: set[str] = set()
    for row in summary_matches:
        tf = str(row.get("timeframe", "")).upper()
        if tf:
            tried_tfs.add(tf)
    tried_tfs.add(timeframe.upper())
    untried_tfs = sorted(_ALL_TIMEFRAMES - tried_tfs)

    if untried_tfs:
        candidates.append(_suggestion(
            f"MODEL={model} untested on {', '.join(untried_tfs)}. "
            f"Different timeframe changes regime dynamics and signal frequency.",
            "EXPLORE", "LOW",
        ))

    # --- Deduplicate by prefix, rank: AVOID > EXPLOIT > EXPLORE, then cap at 3 ---
    _type_rank = {"AVOID": 0, "EXPLOIT": 1, "EXPLORE": 2}
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for s in candidates:
        key = s["text"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(s)

    unique.sort(key=lambda s: _type_rank.get(s["type"], 9))
    return unique[:3]


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------

def _result(
    status: str,
    confidence: str,
    matches_found: int,
    summary: str,
    examples: list[dict[str, Any]],
    recommendation: str,
    suggestions: list[dict[str, str]] | None = None,
    memory_basis: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "confidence": confidence,
        "matches_found": matches_found,
        "summary": summary,
        "examples": examples,
        "recommendation": recommendation,
        "suggestions": suggestions or [],
        "memory_basis": memory_basis or [],
    }


# ---------------------------------------------------------------------------
# Pretty-print for CLI
# ---------------------------------------------------------------------------

def print_evaluation(result: dict[str, Any]) -> None:
    """Print structured evaluation to stdout."""
    status = result["status"]
    confidence = result["confidence"]
    rec = result["recommendation"]
    matches = result["matches_found"]

    indicator = {
        "NEW": "[OK]",
        "REPEAT_PROMISING": "[OK]",
        "REPEAT_WEAK": "[!!]",
        "REPEAT_FAILED": "[XX]",
    }.get(status, "[??]")

    print(f"\n{'='*60}")
    print(f"  IDEA EVALUATION  {indicator}  {status}")
    print(f"{'='*60}")
    print(f"  Confidence:      {confidence}")
    print(f"  Matches found:   {matches}")
    print(f"  Recommendation:  {rec}")
    print(f"  Summary:         {result['summary']}")

    if result["examples"]:
        print(f"\n  Prior runs/findings:")
        for i, ex in enumerate(result["examples"], 1):
            source = ex.get("source", "?")
            if source == "run_summary":
                syms = ex.get("symbols", "")
                verdict = ex.get("verdict", "")
                cand = ex.get("candidate_status", "")
                extra = []
                if verdict:
                    extra.append(f"verdict={verdict}")
                if cand:
                    extra.append(f"cand={cand}")
                extra_str = f"  {'  '.join(extra)}" if extra else ""
                print(f"    {i}. {ex['strategy']}  PF={ex['profit_factor']}  "
                      f"trades={ex['total_trades']}  [{syms}]{extra_str}")
            elif source == "Master_Filter":
                print(f"    {i}. {ex['strategy']}  PF={ex['profit_factor']}  "
                      f"trades={ex['total_trades']}  [Master_Filter]")
            elif source == "hypothesis_log":
                print(f"    {i}. {ex['summary']}  [hypothesis_log]")
            elif source == "hypothesis_log_detail":
                decision = ex.get("decision", "?")
                hyp = ex.get("hypothesis", "?")
                if len(hyp) > 80:
                    hyp = hyp[:80] + "..."
                reason = ex.get("rejection_reason", "")
                pf_str = f"  PF={ex['pf']:.2f}" if ex.get("pf") else ""
                print(f"    {i}. {ex.get('strategy', '?')}  {decision}{pf_str}  [hypothesis]")
                print(f"       {hyp}")
                if reason and decision == "REJECT":
                    print(f"       Reason: {reason[:100]}")
            else:
                finding = ex.get("finding", "")
                if len(finding) > 100:
                    finding = finding[:100] + "..."
                print(f"    {i}. {ex.get('strategy', '?')}  "
                      f"tags=[{ex.get('tags', '')}]  [RESEARCH_MEMORY]")
                if finding:
                    print(f"       {finding}")

    if result.get("suggestions"):
        print(f"\n  Suggested hypothesis changes (advisory only):")
        for i, sug in enumerate(result["suggestions"], 1):
            stype = sug.get("type", "?")
            conf = sug.get("confidence", "?")
            text = sug.get("text", "")
            print(f"    {i}. [{stype}] ({conf})  {text}")

    if result.get("memory_basis"):
        basis = result["memory_basis"]
        parts = [f"{b['source']}={b['entries_used']}" for b in basis]
        print(f"\n  Memory basis:    {', '.join(parts)}")

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Sources report (for --sources flag)
# ---------------------------------------------------------------------------

def print_sources_report() -> None:
    """Print availability status of all data sources."""
    import pandas as pd

    print(f"\n{'='*60}")
    print(f"  IDEA GATE — Data Source Report")
    print(f"{'='*60}")

    # run_summary.csv
    if RUN_SUMMARY_PATH.exists():
        try:
            df = pd.read_csv(RUN_SUMMARY_PATH)
            strategies = df["strategy_id"].nunique() if "strategy_id" in df.columns else 0
            statuses = df["status"].value_counts().to_dict() if "status" in df.columns else {}
            print(f"  run_summary.csv       OK  {len(df)} rows, {strategies} strategies")
            for s, c in statuses.items():
                print(f"    {s}: {c}")
        except Exception as e:
            print(f"  run_summary.csv       ERROR  {e}")
    else:
        print(f"  run_summary.csv       MISSING  {RUN_SUMMARY_PATH}")

    # hypothesis_log.json
    if HYPOTHESIS_LOG_PATH.exists():
        try:
            with open(HYPOTHESIS_LOG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 0
            decisions = {}
            for entry in (data if isinstance(data, list) else []):
                d = entry.get("decision", "unknown")
                decisions[d] = decisions.get(d, 0) + 1
            print(f"  hypothesis_log.json   OK  {count} entries")
            for d, c in decisions.items():
                print(f"    {d}: {c}")
        except Exception as e:
            print(f"  hypothesis_log.json   ERROR  {e}")
    else:
        print(f"  hypothesis_log.json   MISSING  {HYPOTHESIS_LOG_PATH}")

    # RESEARCH_MEMORY
    for fn in ("RESEARCH_MEMORY.md", "RESEARCH_MEMORY_ARCHIVE.md"):
        path = PROJECT_ROOT / fn
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                entries = _parse_research_entries(text)
                print(f"  {fn:<24s} OK  {len(entries)} entries")
            except Exception as e:
                print(f"  {fn:<24s} ERROR  {e}")
        else:
            print(f"  {fn:<24s} MISSING")

    # Master Filter (DB-first, Excel fallback)
    try:
        from tools.ledger_db import read_master_filter
        df = read_master_filter()
        if not df.empty:
            print(f"  Master_Filter         OK  {len(df)} rows  (ledger_db)")
        else:
            print(f"  Master_Filter         EMPTY  (ledger_db)")
    except Exception as e:
        print(f"  Master_Filter         ERROR  {e}")

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight Idea Evaluation — Concept Reuse Gate v1"
    )
    parser.add_argument("directive_path", nargs="?",
                        help="Path to directive YAML (.txt) file")
    parser.add_argument(
        "--strict-preflight", action="store_true",
        help="If set, REPEAT_FAILED status causes exit code 1 (blocking)."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of formatted text."
    )
    parser.add_argument(
        "--sources", action="store_true",
        help="Print data source availability report and exit."
    )
    args = parser.parse_args()

    if args.sources:
        print_sources_report()
        return 0

    if not args.directive_path:
        parser.error("directive_path is required (unless --sources)")

    result = evaluate_idea(args.directive_path)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_evaluation(result)

    # Gate output line (consistent with other gates)
    status = result["status"]
    rec = result["recommendation"]
    matches = result["matches_found"]

    if status == "REPEAT_FAILED" and args.strict_preflight:
        print(f"[IDEA_GATE] FAIL: {status} — {result['summary']}")
        return 1

    # Non-blocking: always PASS with advisory
    label = "WARN" if rec in ("RECONSIDER", "PROCEED_WITH_CAUTION") else "PASS"
    print(f"[IDEA_GATE] {label}: status={status} matches={matches} rec={rec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
