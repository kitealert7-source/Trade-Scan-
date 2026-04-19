"""
tools/generate_strategy_card.py

Generates STRATEGY_CARD.md in every backtest symbol folder for a given directive.

Sections:
  1. Run Identity    — strategy, symbol, timeframe, sweep/pass, run_id, engine
  2. Configuration   — all tunable parameters from STRATEGY_SIGNATURE (flat table)
  3. Active Logic    — compact one-liners (entry, exit, filters)
  4. Changes from Previous Run — diff vs P(n-1); fallback to last pass of S(n-1)

Called from run_stage1.py after each successful backtest.
Also callable as a standalone backfill tool (see bottom __main__ block).
Always overwrites. Non-blocking — prints errors, never raises.
"""

import re
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

from config.state_paths import RUNS_DIR, BACKTESTS_DIR
from tools.pipeline_utils import get_engine_version, PROJECT_ROOT

# Keys excluded from the config table (structural / non-tunable)
_SKIP_KEYS     = {"indicators", "signature_version"}
_SKIP_VAL_KEYS = {"type", "condition"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten(obj, prefix="", out=None):
    """Recursively flatten STRATEGY_SIGNATURE into {dotted.key: value}."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS or k in _SKIP_VAL_KEYS:
                continue
            fk = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _flatten(v, fk, out)
            elif not isinstance(v, list):
                out[fk] = v
    return out


def _parse_name(name):
    """Return (prefix, sweep, version, pass_n) or None."""
    m = re.search(r'^(.*?)_S(\d+)_V(\d+)_P(\d+)$', name)
    return (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _find_spy(name, runs_root):
    """Find strategy.py whose Strategy.name matches `name`.

    Search order:
      1. TradeScan_State/runs/<run_id>/strategy.py  (post-pipeline snapshots)
      2. Trade_Scan/strategies/<name>/strategy.py    (pre-approval staging)

    Handles both `name = "..."` and `name      = "..."` (aligned older style).
    """
    pattern = re.compile(r'\bname\s*=\s*["\']' + re.escape(name) + r'["\']')

    # 1. Runs archive (primary)
    for d in runs_root.iterdir():
        if not d.is_dir():
            continue
        spy = d / "strategy.py"
        if spy.exists():
            try:
                if pattern.search(spy.read_text(encoding="utf-8")):
                    return spy
            except Exception:
                pass

    # 2. Trade_Scan/strategies/<name>/ (pre-approval staging fallback)
    staging = PROJECT_ROOT / "strategies" / name / "strategy.py"
    if staging.exists():
        try:
            if pattern.search(staging.read_text(encoding="utf-8")):
                return staging
        except Exception:
            pass

    return None


def _extract_sig(source):
    """Extract and parse STRATEGY_SIGNATURE dict from strategy.py source."""
    m = re.search(
        r'# --- STRATEGY SIGNATURE START ---\s*(.*?)\s*# --- STRATEGY SIGNATURE END ---',
        source, re.DOTALL,
    )
    if not m:
        return {}
    text = re.sub(r'^STRATEGY_SIGNATURE\s*=\s*', '', m.group(1).strip())
    try:
        return ast.literal_eval(text)
    except Exception:
        return {}


def _diff(prev_sig, curr_sig):
    """Return [(key, prev_val, curr_val)] for every changed/added/removed field."""
    p, c = _flatten(prev_sig), _flatten(curr_sig)
    rows = []
    for k in sorted(set(p) | set(c)):
        pv, cv = p.get(k, "—"), c.get(k, "—")
        if pv != cv:
            rows.append((k, str(pv), str(cv)))
    return rows


def _logic_lines(sig):
    """Build compact Active Logic lines from STRATEGY_SIGNATURE."""
    lines  = []
    er     = sig.get("execution_rules", {})
    el     = er.get("entry_logic", {})
    sl     = er.get("stop_loss", {})
    tp     = er.get("take_profit", {})
    trl    = er.get("trailing_stop", {})
    xl     = er.get("exit_logic", {})
    mr     = sig.get("mean_reversion_rules", {})
    mre    = mr.get("entry", {})
    mrx    = mr.get("exit", {})
    tf     = sig.get("trend_filter", {})
    vf     = sig.get("volatility_filter", {})
    sf     = sig.get("session_filter", {})
    timing = sig.get("order_placement", {}).get("execution_timing", "next_bar_open")

    if el.get("type") == "spike_fade":
        lines.append(
            f"Entry: spike_fade | move > {el.get('spike_atr_multiplier','?')}×ATR"
            f" | {el.get('direction','both')} | confirm {el.get('confirmation','close')} | {timing}"
        )
    elif mre:
        lines.append(
            f"Entry: rsi_avg_pullback | RSI({mre.get('rsi_period',2)}) avg"
            f" < {mre.get('long_threshold',25)} / > {mre.get('short_threshold',75)}"
            f" | trend_score abs≥{mre.get('min_abs_trend_score',2)} | {timing}"
        )

    xp = []
    if tp.get("enabled", True) and tp.get("atr_multiplier"):
        xp.append(f"TP {tp['atr_multiplier']}×ATR")
    elif tp.get("enabled") is False:
        xp.append("TP off")
    if sl.get("atr_multiplier"):
        xp.append(f"SL {sl['atr_multiplier']}×ATR")
    if mrx.get("rsi_exit_long") is not None:
        xp.append(f"RSI exit L≥{mrx['rsi_exit_long']}/S≤{mrx['rsi_exit_short']}")
    bars = xl.get("time_exit_bars") or mrx.get("max_bars")
    if bars:
        xp.append(f"time {bars}b")
    if trl.get("enabled"):
        xp.append("trail on")
    if xp:
        lines.append("Exit: " + " | ".join(xp))

    if tf.get("enabled"):
        lw = tf.get("long_when", {})
        if tf.get("direction_gate") and lw:
            lines.append(
                f"Trend: direction_gate"
                f" | L score≥{lw.get('required_regime', 2)}"
                f" / S score≤{tf.get('short_when', {}).get('required_regime', -2)}"
            )
        else:
            parts = []
            ex = tf.get("exclude_regime")
            if ex is not None:
                parts.append(f"exclude regime {ex}")
            req = tf.get("required_regime")
            if req is not None:
                parts.append(f"abs {tf.get('operator','?')} {req}")
            lines.append("Trend: " + (" | ".join(parts) if parts else "enabled"))

    if vf:
        if vf.get("threshold") is not None:
            lines.append(
                f"Volatility: ATR pct > {vf['threshold']}th"
                f" | {vf.get('atr_percentile_lookback','?')}-bar window"
            )
        elif vf.get("required_regime") is not None:
            rm = {-1: "low", 0: "normal", 1: "high"}
            r = vf["required_regime"]
            lines.append(f"Volatility: regime = {r} ({rm.get(r, r)})")

    if sf and sf.get("enabled") and sf.get("allowed_sessions"):
        lines.append(f"Session: {', '.join(sf['allowed_sessions'])}")

    return lines


# ── Hypothesis & Testing Logic ────────────────────────────────────────────────

_DIRECTIVE_SUBDIRS = ["completed", "active_backup", "active", "INBOX"]


def _find_directive(directive_name):
    """Locate the directive .txt file for a strategy across all directive subdirs."""
    base = PROJECT_ROOT / "backtest_directives"
    for sub in _DIRECTIVE_SUBDIRS:
        d = base / sub
        if not d.exists():
            continue
        for suffix in [".txt", ".txt.admitted"]:
            f = d / f"{directive_name}{suffix}"
            if f.exists() and f.stat().st_size > 10:
                return f
    return None


def _directive_description(directive_name):
    """Return the description: field from the directive file, or None."""
    f = _find_directive(directive_name)
    if not f:
        return None
    try:
        content = f.read_text(encoding="utf-8")
        m = re.search(r'description:\s*"([^"]+)"', content)
        if m:
            return m.group(1).strip()
        m = re.search(r"description:\s*'([^']+)'", content)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


def _model_token(directive_name):
    """Extract model token (e.g. SPKFADE, RSIAVG) from directive name."""
    m = re.search(r'_(?:15M|30M|1H|4H|1D|1W)_([A-Z]+)', directive_name)
    return m.group(1) if m else None


_HYPOTHESIS_MAP = {
    "SPKFADE": [
        "Abnormally large bar moves are often driven by temporary momentum — stop runs, news spikes, or liquidity voids — rather than genuine directional conviction.",
        "After the spike, price tends to partially reverse as the imbalance resolves and trapped participants exit.",
        "The edge is in fading the overextension, not joining it.",
    ],
    "RSIAVG": [
        "In a confirmed trending market, short-term pullbacks are counter-trend noise, not reversals.",
        "When RSI reaches an extreme during a strong trend, it typically signals brief exhaustion that resolves back in the trend direction.",
        "The edge is in entering the pullback before it snaps back, staying aligned with the dominant order flow.",
    ],
    "FAKEBREAK": [
        "Resting stops cluster just beyond visible price levels — highs, lows, and range boundaries.",
        "When price pierces these levels intrabar but closes back inside, it triggered the stops without genuine follow-through.",
        "The trapped breakout traders become fuel for a reversal. The edge is in entering that reversal early.",
    ],
    "LIQSWEEP": [
        "Liquidity pools sit above prior highs and below prior lows where retail stops accumulate.",
        "Large participants sweep these levels to fill their own orders, creating a sharp move that quickly reverses once the liquidity is absorbed.",
        "The edge is in recognising the sweep as a fill event, not a directional breakout.",
    ],
    "IMPULSE": [
        "When institutional order flow enters, it leaves a momentum signature — a strong, decisive move that tends to continue in the near term.",
        "Session bias and regime direction filter confirm the impulse is aligned with dominant market structure.",
        "The edge is in joining confirmed momentum early, before the move matures.",
    ],
    "PINBAR": [
        "A pin bar shows that price tested a level and was firmly rejected — the wick represents failed supply or demand.",
        "The rejection traps traders who entered in the wick direction; their forced exits fuel the reversal.",
        "The edge is in entering at the close of the rejection bar before the reversal accelerates.",
    ],
    "BOS": [
        "A confirmed break of a prior structural level signals a genuine shift in the order flow balance.",
        "Price that breaks and holds beyond a key level attracts continuation as late participants enter and trapped traders exit.",
        "The edge is in entering on confirmed structure breaks, not anticipating them.",
    ],
    "VOLEXP": [
        "Volatility compression is a precursor to directional expansion — markets coil before they move.",
        "When ATR breaks out of a compressed range, it signals a new directional move beginning with enough momentum to sustain direction.",
        "The edge is in entering early in the expansion, before the trend is obvious.",
    ],
    "MICROREV": [
        "Within a session, RSI extremes on short timeframes tend to snap back quickly before the next directional move.",
        "These micro-reversions are driven by short-term imbalances that attract counter-flow as overextended moves stall.",
        "The edge is narrow and fast: capturing the snap-back before the next impulse begins.",
    ],
    "ASRANGE": [
        "The Asian session establishes a reference range representing overnight equilibrium.",
        "Deviations from this range during London and early NY sessions often revert, before new directional flow takes over.",
        "The edge is in fading moves outside the Asian range during the reversion window.",
    ],
    "DAYOC": [
        "The relationship between a day's open and close has a directional bias that varies by regime and session.",
        "In certain market conditions, the intraday direction from the open tends to persist or revert in a predictable pattern.",
        "The edge is in aligning with the dominant open-to-close bias under the right conditions.",
    ],
}


def _hypothesis(directive_name):
    """Return hypothesis lines for directive, or fallback."""
    token = _model_token(directive_name)
    return _HYPOTHESIS_MAP.get(token, ["[UNAVAILABLE]"])


_ENTRY_FALLBACK = {
    "FAKEBREAK": "Enter the reversal when an intrabar breakout closes back inside the range, filtered by regime and volatility.",
    "LIQSWEEP":  "Enter the reversal after a liquidity sweep of a prior high or low, confirmed by a close back inside the range.",
    "IMPULSE":   "Enter in the direction of a momentum impulse, aligned with trend regime and session direction filter.",
    "PINBAR":    "Enter in the body direction after a confirmed pin bar rejection, filtered by trend regime.",
    "BOS":       "Enter on a confirmed structural break in the breakout direction, with regime filter active.",
    "VOLEXP":    "Enter in the direction of volatility expansion when ATR breaks above its historical range, filtered by trend.",
    "MICROREV":  "Enter counter to RSI extremes within a session, expecting a fast snap-back.",
    "ASRANGE":   "Enter against a deviation from the Asian session range during the London or NY session.",
    "DAYOC":     "Enter at the open in the direction of the intraday bias, filtered by regime and session.",
}


def _testing_logic(sig, directive_name):
    """Return 1-2 line execution description.
    Prefers the researcher-written directive description over auto-generation.
    No parameter values — indicator names and directional logic only.
    """
    # Prefer directive description (researcher-written, most accurate)
    desc = _directive_description(directive_name)
    if desc:
        return [desc]

    token = _model_token(directive_name)
    er  = sig.get("execution_rules", {})
    el  = er.get("entry_logic", {})
    sl  = er.get("stop_loss", {})
    tp  = er.get("take_profit", {})
    trl = er.get("trailing_stop", {})
    xl  = er.get("exit_logic", {})
    mr  = sig.get("mean_reversion_rules", {})
    mre = mr.get("entry", {})
    mrx = mr.get("exit", {})
    tf  = sig.get("trend_filter", {})
    vf  = sig.get("volatility_filter", {})

    # Entry
    if el.get("type") == "spike_fade":
        filters = []
        if tf.get("enabled"):
            filters.append("trend filter")
        if vf:
            filters.append("volatility filter")
        fstr = f", screened by {' and '.join(filters)}" if filters else ""
        entry = f"Enter counter-trend after an abnormal bar close{fstr} — short on a spike up, long on a spike down."
    elif mre:
        dir_desc = "long in uptrend / short in downtrend" if tf.get("direction_gate") else "long and short"
        vol_note = " Only in low-volatility conditions." if vf.get("required_regime") == -1 else ""
        entry = f"Enter on RSI exhaustion in the pullback direction ({dir_desc}), confirmed by trend filter.{vol_note}"
    else:
        entry = _ENTRY_FALLBACK.get(token, "[UNAVAILABLE]")

    # Exit
    xp = []
    if tp.get("enabled", True) and tp.get("atr_multiplier"):
        xp.append("ATR take profit")
    if mrx.get("rsi_exit_long") is not None:
        xp.append("RSI reversion")
    if sl.get("atr_multiplier"):
        xp.append("ATR stop loss")
    if xl.get("time_exit_bars") or mrx.get("max_bars"):
        xp.append("time exit")
    if trl.get("enabled"):
        xp.append("trailing stop")
    exit_line = ("Exit via " + ", ".join(xp) + ".") if xp else ""

    return [line for line in [entry, exit_line] if line]


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_strategy_card(
    directive_name: str,
    backtest_root: Path,
    strategy_py_path: Path,
    runs_root: Path,
) -> None:
    """
    Generate STRATEGY_CARD.md in every backtest symbol folder for directive_name.
    Always overwrites. Non-blocking — prints errors, never raises.
    """
    if not strategy_py_path.exists():
        print(f"[STRATEGY_CARD] strategy.py not found at {strategy_py_path} — skipping")
        return

    source = strategy_py_path.read_text(encoding="utf-8")
    sig = _extract_sig(source)
    if not sig:
        print(f"[STRATEGY_CARD] STRATEGY_SIGNATURE not parseable for {directive_name} — skipping")
        return

    sym_dirs = sorted([
        d for d in backtest_root.iterdir()
        if d.is_dir() and d.name.startswith(f"{directive_name}_")
    ])
    if not sym_dirs:
        print(f"[STRATEGY_CARD] No symbol dirs found for {directive_name} — skipping")
        return

    tf_m = re.search(r'timeframe\s*=\s*["\']([^"\']+)["\']', source)
    timeframe = tf_m.group(1).upper() if tf_m else "?"
    try:
        engine_ver = get_engine_version()
    except Exception:
        engine_ver = "?"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parsed = _parse_name(directive_name)
    if parsed:
        prefix, sweep, version, pass_n = parsed
        sweep_str, pass_str = f"S{sweep:02d}", f"P{pass_n:02d}"
    else:
        prefix = sweep = version = pass_n = None
        sweep_str = pass_str = "?"

    flat       = _flatten(sig)
    logic      = _logic_lines(sig)
    hypothesis = _hypothesis(directive_name)
    testing    = _testing_logic(sig, directive_name)

    # ── Delta ─────────────────────────────────────────────────────────────────
    _unavail   = "Previous run unavailable — full configuration shown without diff baseline."
    delta_label = ""
    delta_rows  = []
    delta_note  = ""

    if parsed is None:
        delta_label = _unavail
    elif pass_n == 0 and sweep == 0:
        delta_label = "Initial run — no previous pass."
    else:
        if pass_n > 0:
            prev_name  = f"{prefix}_S{sweep:02d}_V{version}_P{pass_n - 1:02d}"
            prev_label = f"S{sweep:02d}_V{version}_P{pass_n - 1:02d}"
        else:
            # P00 — find last pass of S(sweep-1) from backtest_root
            ps  = sweep - 1
            pat = f"{prefix}_S{ps:02d}_V{version}_P"
            names = set()
            for d in backtest_root.iterdir():
                if d.is_dir() and d.name.startswith(pat):
                    m = re.match(r'^(.+_P\d+)_[^_]+$', d.name)
                    if m:
                        names.add(m.group(1))
            if names:
                def _pnum(n):
                    m2 = re.search(r'_P(\d+)$', n)
                    return int(m2.group(1)) if m2 else -1
                prev_name  = max(names, key=_pnum)
                prev_label = prev_name.split(f"{prefix}_", 1)[-1]
            else:
                prev_name  = None
                prev_label = f"S{ps:02d} last pass"

        if prev_name:
            prev_spy = _find_spy(prev_name, runs_root)
            if prev_spy:
                prev_sig    = _extract_sig(prev_spy.read_text(encoding="utf-8"))
                delta_rows  = _diff(prev_sig, sig)
                delta_label = f"{prev_label} → {sweep_str}_V{version}_{pass_str}"
                if not delta_rows:
                    delta_note = "No strategy configuration changes — pass variation (symbol/coverage)."
            else:
                delta_label = _unavail
        else:
            delta_label = _unavail

    # ── Write card per symbol dir ──────────────────────────────────────────────
    for s_dir in sym_dirs:
        symbol = s_dir.name[len(directive_name) + 1:]

        run_id   = strategy_py_path.parent.name  # fallback
        meta_dir = s_dir / "metadata"
        if meta_dir.exists():
            for mf in meta_dir.glob("*.json"):
                try:
                    run_id = json.loads(mf.read_text(encoding="utf-8")).get("run_id", run_id)
                    break
                except Exception:
                    pass

        md = [
            f"# STRATEGY CARD — {directive_name}",
            "",
            (
                f"**Symbol:** {symbol}  |  **Timeframe:** {timeframe}  |  "
                f"**Sweep:** {sweep_str}  |  **Pass:** {pass_str}  |  "
                f"**Run ID:** `{run_id}`  |  **Engine:** {engine_ver}  |  **Generated:** {generated_at}"
            ),
            "", "---", "",
            "## Configuration", "",
            "| Parameter | Value |",
            "|-----------|-------|",
        ]
        for k, v in sorted(flat.items()):
            val = "yes" if v is True else ("no" if v is False else str(v))
            md.append(f"| `{k}` | {val} |")

        md += ["", "## Active Logic", ""]
        md += logic

        md += ["", "## Hypothesis", ""]
        md += hypothesis

        md += ["", "## Testing Logic", ""]
        md += testing

        md += [
            "", "## Changes from Previous Run", "",
            f"*{delta_label}*", "",
        ]
        if delta_rows:
            md += ["| Field | Previous | This Run |", "|-------|----------|---------|"]
            for field, pv, cv in delta_rows:
                md.append(f"| `{field}` | {pv} | {cv} |")
        elif delta_note:
            md.append(delta_note)

        md += ["", "---", "*Auto-generated — do not edit. Regenerated on every pipeline run.*"]

        out = s_dir / "STRATEGY_CARD.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        print(f"[STRATEGY_CARD] {out}")


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate STRATEGY_CARD.md for a directive.")
    parser.add_argument("directive_name", help="e.g. 11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S03_V1_P00")
    args = parser.parse_args()

    spy = _find_spy(args.directive_name, RUNS_DIR)
    if not spy:
        print(f"[STRATEGY_CARD] strategy.py not found for {args.directive_name}")
        raise SystemExit(1)

    generate_strategy_card(args.directive_name, BACKTESTS_DIR, spy, RUNS_DIR)
