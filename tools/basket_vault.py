"""basket_vault.py — N-symbol DRY_RUN_VAULT extension for basket directives.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 6 (Section 7-8).

Per-symbol vault layout (UNCHANGED — Phase 6 must not break this):
    DRY_RUN_VAULT/DRY_RUN_<DATE>__<hash>/<strategy_id>/
        strategy.py
        deployable/<PROFILE>/deployable_trade_log.csv
        meta.json
        portfolio_metadata.json
        ...

Basket vault layout (NEW in Phase 6):
    DRY_RUN_VAULT/DRY_RUN_<DATE>__<hash>/<basket_id>/
        basket.yaml             # frozen directive snapshot (immutable)
        basket_meta.json        # rule_name@version, harvested_total, basket_id
        recycle_events.jsonl    # one JSON object per recycle event (ordered)
        legs/<SYMBOL>/
            leg_metadata.yaml   # symbol, lot, direction
            trade_log.csv       # per-leg trade list

Detection: a vault is a basket vault iff `basket.yaml` is present at its root.
Per-symbol vaults never have that file; back-compatibility is automatic.

Round-trip guarantee:
    write_basket_vault(out_dir, directive, result) writes the layout.
    read_basket_vault(out_dir) returns the same data structure.
    A test (test_basket_vault_phase6.py) verifies the round trip is lossless.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class BasketVaultPayload:
    """In-memory representation of a basket vault folder."""
    basket_id:           str
    directive:           dict[str, Any]                     # frozen directive
    rule_name:           str
    rule_version:        int
    harvested_total_usd: float
    legs:                list[dict[str, Any]] = field(default_factory=list)
    leg_trades:          dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recycle_events:      list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def is_basket_vault(vault_strategy_dir: Path) -> bool:
    """A vault subfolder is a basket vault iff it contains `basket.yaml`."""
    return (vault_strategy_dir / "basket.yaml").is_file()


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_basket_vault(out_dir: Path, payload: BasketVaultPayload) -> Path:
    """Materialize a basket vault under out_dir/<basket_id>/.

    Returns the path of the created basket vault directory.

    Idempotency: if `out_dir/<basket_id>/` already exists, it is REMOVED
    and recreated from scratch. Append-only invariants do not apply to
    vault directories (they are write-once snapshots; re-writing reflects
    a re-run, which gets a fresh vault dir via the caller's hash logic).
    """
    base = out_dir / payload.basket_id
    if base.exists():
        shutil.rmtree(base)
    legs_root = base / "legs"
    legs_root.mkdir(parents=True, exist_ok=True)

    # basket.yaml — frozen directive snapshot
    with open(base / "basket.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(payload.directive, f, sort_keys=False, default_flow_style=False)

    # basket_meta.json
    meta = {
        "basket_id":           payload.basket_id,
        "rule_name":           payload.rule_name,
        "rule_version":        payload.rule_version,
        "harvested_total_usd": payload.harvested_total_usd,
        "leg_symbols":         [l["symbol"] for l in payload.legs],
        "leg_count":           len(payload.legs),
        "trade_total":         sum(len(t) for t in payload.leg_trades.values()),
        "recycle_event_count": len(payload.recycle_events),
    }
    with open(base / "basket_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True, default=str)

    # recycle_events.jsonl
    with open(base / "recycle_events.jsonl", "w", encoding="utf-8") as f:
        for ev in payload.recycle_events:
            f.write(json.dumps(ev, default=str) + "\n")

    # legs/<SYM>/{leg_metadata.yaml, trade_log.csv}
    leg_by_sym = {l["symbol"]: l for l in payload.legs}
    for sym, trades in payload.leg_trades.items():
        leg_dir = legs_root / sym
        leg_dir.mkdir(parents=True, exist_ok=True)
        with open(leg_dir / "leg_metadata.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(leg_by_sym.get(sym, {"symbol": sym}), f,
                           sort_keys=False, default_flow_style=False)
        if trades:
            pd.DataFrame(trades).to_csv(leg_dir / "trade_log.csv", index=False)
        else:
            (leg_dir / "trade_log.csv").write_text("", encoding="utf-8")
    return base


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def read_basket_vault(base: Path) -> BasketVaultPayload:
    """Read a basket vault folder back into a BasketVaultPayload."""
    if not is_basket_vault(base):
        raise ValueError(f"basket_vault: {base} is not a basket vault (no basket.yaml).")

    with open(base / "basket.yaml", encoding="utf-8") as f:
        directive = yaml.safe_load(f) or {}
    with open(base / "basket_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    events: list[dict[str, Any]] = []
    events_path = base / "recycle_events.jsonl"
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    legs_root = base / "legs"
    leg_meta: list[dict[str, Any]] = []
    leg_trades: dict[str, list[dict[str, Any]]] = {}
    if legs_root.is_dir():
        for leg_dir in sorted(legs_root.iterdir()):
            if not leg_dir.is_dir():
                continue
            sym = leg_dir.name
            meta_path = leg_dir / "leg_metadata.yaml"
            if meta_path.is_file():
                with open(meta_path, encoding="utf-8") as f:
                    leg_meta.append(yaml.safe_load(f) or {"symbol": sym})
            log_path = leg_dir / "trade_log.csv"
            if log_path.is_file() and log_path.stat().st_size > 0:
                df = pd.read_csv(log_path)
                leg_trades[sym] = df.to_dict(orient="records")
            else:
                leg_trades[sym] = []

    return BasketVaultPayload(
        basket_id=meta["basket_id"],
        directive=directive,
        rule_name=meta["rule_name"],
        rule_version=meta["rule_version"],
        harvested_total_usd=meta["harvested_total_usd"],
        legs=leg_meta,
        leg_trades=leg_trades,
        recycle_events=events,
    )


__all__ = [
    "BasketVaultPayload",
    "is_basket_vault",
    "write_basket_vault",
    "read_basket_vault",
]
