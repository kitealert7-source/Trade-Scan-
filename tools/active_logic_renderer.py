"""
active_logic_renderer.py — single source of truth for human-readable "Active Logic".

Renders a strategy STRATEGY_SIGNATURE (single-asset) OR a basket config block into
compact, deterministic ``Label: key=value | ...`` lines, reading ONLY fields that are
actually present. It invents NOTHING — no default RSI periods, thresholds, trend scores,
or primitive names. This is an AUDIT surface: faithful to the declared signature, verbose
over silently-dropped semantics, stable under re-rendering.

Consumed by BOTH ``tools/generate_strategy_card.py`` and ``tools/basket_report.py`` so the
two human-facing reports cannot diverge. Replaces the prior hardcoded per-strategy
templates that mislabeled every strategy they were not written for.

Contract / guarantees:
  - Only fields present in the input are rendered (no defaults, no invented values).
  - Deterministic: keys sorted lexicographically; output is independent of dict order.
  - Idempotent: ``render(render(sig)) == render(sig)`` — feeding the canonical line list
    back in returns it unchanged (it is already canonical).
  - No empty container tokens: transparent wrappers (e.g. ``params``) are flattened
    (``param_<key>``), never emitted as a bare ``params`` token.
  - Explicitly-disabled toggles (``enabled: false`` for TP / trailing) contribute no
    tokens — the absence of that logic, not an invented description.
"""
from __future__ import annotations

# Structural wrappers flattened into ``<prefix><key>=value`` rather than emitted as a
# bare grouping token. Direction keys (long/short) are NOT here — they are meaningful.
_TRANSPARENT = {"params": "param_"}


def _fmt_val(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        return ",".join(_fmt_val(x) for x in v)
    return str(v)


def _tokens(obj) -> list[str]:
    """Flatten a config value into deterministic display tokens (sorted keys).

    - scalar                 -> ['<value>']
    - {k: scalar}            -> ['k=<value>']
    - {wrapper: {..}}        -> ['<prefix>k=<value>', ...]   (wrapper flattened, no bare token)
    - {group: {..}}          -> ['group', <tokens of sub-dict>]   (group as a bare token)
    None / empty values are skipped.
    """
    toks: list[str] = []
    if not isinstance(obj, dict):
        if obj is not None and obj != "":
            toks.append(_fmt_val(obj))
        return toks
    for k in sorted(obj.keys(), key=str):
        v = obj[k]
        if isinstance(v, dict):
            if not v:
                continue
            if k in _TRANSPARENT:
                prefix = _TRANSPARENT[k]
                for kk in sorted(v.keys(), key=str):
                    sub = _tokens({kk: v[kk]})
                    toks.extend(f"{prefix}{t}" for t in sub)
            else:
                toks.append(str(k))            # meaningful grouping (e.g. 'long')
                toks.extend(_tokens(v))
        elif isinstance(v, (list, tuple)):
            if len(v):
                toks.append(f"{k}={_fmt_val(v)}")
        elif v is not None:
            toks.append(f"{k}={_fmt_val(v)}")
    return toks


def render_active_logic(sig) -> list[str]:
    """Return ``Label: ...`` Active-Logic lines for a single-asset signature or basket
    block. Reads only what is present; invents nothing. Idempotent on its own output."""
    if isinstance(sig, list):                  # already-rendered canonical lines
        return [str(x) for x in sig]
    if not isinstance(sig, dict):
        return []
    lines: list[str] = []

    er = sig.get("execution_rules") or {}
    mr = sig.get("mean_reversion_rules") or {}
    timing = (sig.get("order_placement") or {}).get("execution_timing")

    # ── Entry ──────────────────────────────────────────────────────────────
    entry = mr.get("entry") or er.get("entry_logic")
    if entry:
        toks = _tokens(entry)
        if timing:
            toks.append(_fmt_val(timing))
        lines.append("Entry: " + " | ".join(toks))

    # ── Exit (aggregate exit rules + stop / TP / trailing, disambiguated) ───
    exit_cfg: dict = dict(mr.get("exit") or {})
    exit_cfg.update(er.get("exit_logic") or {})
    for k, v in (er.get("stop_loss") or {}).items():
        exit_cfg[f"sl_{k}"] = v
    tp = er.get("take_profit") or {}
    if tp.get("enabled", False):
        for k, v in tp.items():
            if k != "enabled":
                exit_cfg[f"tp_{k}"] = v
    trl = er.get("trailing_stop") or {}
    if trl.get("enabled", False):
        for k, v in trl.items():
            if k != "enabled":
                exit_cfg[f"trail_{k}"] = v
    if exit_cfg:
        lines.append("Exit: " + " | ".join(_tokens(exit_cfg)))

    # ── Filters (single-asset) ─────────────────────────────────────────────
    for key, label in (("trend_filter", "Trend"),
                       ("volatility_filter", "Volatility"),
                       ("session_filter", "Session")):
        f = sig.get(key)
        if f:
            lines.append(f"{label}: " + " | ".join(_tokens(f)))

    # ── Basket sections ────────────────────────────────────────────────────
    rr = sig.get("recycle_rule")
    if rr:
        if isinstance(rr, dict) and rr.get("name"):
            # Canonical "name@version" head (matches the legacy basket card), then any
            # remaining keys (params, etc.) flattened as sorted tokens after it.
            ver = rr.get("version", rr.get("mode"))
            head = f"{rr['name']}@{ver}" if ver is not None else str(rr["name"])
            rest = {k: v for k, v in rr.items() if k not in ("name", "version", "mode")}
            lines.append("Rule: " + " | ".join([head] + _tokens(rest)))
        else:
            lines.append("Rule: " + " | ".join(_tokens(rr)))
    rg = sig.get("regime_gate")
    if rg:
        if {"factor", "operator", "value"} <= set(rg):
            lines.append(f"Gate: {rg['factor']} {rg['operator']} {rg['value']}")
        else:
            lines.append("Gate: " + " | ".join(_tokens(rg)))
    basket_extra = {k: sig[k] for k in
                    ("initial_stake_usd", "harvest_threshold_usd",
                     "harvest_target_usd", "trigger_usd") if k in sig}
    if basket_extra:
        lines.append("Basket: " + " | ".join(_tokens(basket_extra)))

    return lines
