"""Phase 6 acceptance test — basket vault round-trip + per-symbol back-compat.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 6.

Gate per migration risk table:
  > MEDIUM risk: "Existing promotions still work; basket vault produced"
  > Mitigation: "Revert vault extension"

Tests:
  - write_basket_vault produces the documented layout
  - read_basket_vault round-trips a BasketVaultPayload losslessly
  - is_basket_vault correctly classifies per-symbol vs basket vault dirs
  - per-symbol vault folders (no basket.yaml) are NOT misclassified as baskets
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.basket_vault import (
    BasketVaultPayload,
    is_basket_vault,
    read_basket_vault,
    write_basket_vault,
)


def _sample_payload() -> BasketVaultPayload:
    return BasketVaultPayload(
        basket_id="H2",
        directive={"test": {"name": "90_PORT_H2_5M_RECYCLE_S01_V1_P00"},
                   "basket": {"basket_id": "H2", "legs": [
                       {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
                       {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
                   ]}},
        rule_name="H2_v7_compression",
        rule_version=1,
        harvested_total_usd=137.42,
        legs=[
            {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
        ],
        leg_trades={
            "EURUSD": [{"entry_index": 0, "exit_index": 50, "direction": 1,
                        "entry_price": 1.10, "exit_price": 1.115,
                        "exit_source": "BASKET_RECYCLE", "exit_reason": "H2_v7_compression"}],
            "USDJPY": [{"entry_index": 0, "exit_index": 50, "direction": -1,
                        "entry_price": 150.0, "exit_price": 147.0,
                        "exit_source": "BASKET_RECYCLE", "exit_reason": "H2_v7_compression"}],
        },
        recycle_events=[
            {"bar_index": 50, "bar_ts": "2024-09-02T04:10:00",
             "factor_value": 15.0, "floating_pnl_usd": 50.5,
             "harvested_total": 50.5,
             "leg_closes": {"EURUSD": 1.115, "USDJPY": 147.0},
             "leg_actions": [{"symbol": "EURUSD", "action": "closed_for_recycle"}]},
        ],
    )


def test_write_basket_vault_layout(tmp_path: Path):
    payload = _sample_payload()
    base = write_basket_vault(tmp_path, payload)
    assert base == tmp_path / "H2"
    assert (base / "basket.yaml").is_file()
    assert (base / "basket_meta.json").is_file()
    assert (base / "recycle_events.jsonl").is_file()
    assert (base / "legs" / "EURUSD" / "leg_metadata.yaml").is_file()
    assert (base / "legs" / "EURUSD" / "trade_log.csv").is_file()
    assert (base / "legs" / "USDJPY" / "leg_metadata.yaml").is_file()
    assert (base / "legs" / "USDJPY" / "trade_log.csv").is_file()


def test_read_round_trips_payload(tmp_path: Path):
    payload = _sample_payload()
    base = write_basket_vault(tmp_path, payload)
    restored = read_basket_vault(base)
    assert restored.basket_id == payload.basket_id
    assert restored.rule_name == payload.rule_name
    assert restored.rule_version == payload.rule_version
    assert restored.harvested_total_usd == payload.harvested_total_usd
    assert restored.directive == payload.directive
    assert {l["symbol"] for l in restored.legs} == {"EURUSD", "USDJPY"}
    # Per-leg trades round-trip via CSV; verify content equivalence
    assert set(restored.leg_trades.keys()) == {"EURUSD", "USDJPY"}
    for sym, src in payload.leg_trades.items():
        got = restored.leg_trades[sym]
        assert len(got) == len(src)
        for src_row, got_row in zip(src, got):
            for key in ("entry_index", "exit_index", "direction"):
                assert int(got_row[key]) == int(src_row[key])
            for key in ("entry_price", "exit_price"):
                assert float(got_row[key]) == pytest.approx(float(src_row[key]))
            for key in ("exit_source", "exit_reason"):
                assert str(got_row[key]) == str(src_row[key])
    assert len(restored.recycle_events) == 1
    ev = restored.recycle_events[0]
    assert ev["bar_index"] == 50
    assert ev["factor_value"] == 15.0


def test_is_basket_vault_detection(tmp_path: Path):
    # Empty dir = not a basket vault
    empty = tmp_path / "EMPTY_VAULT_DIR"
    empty.mkdir()
    assert not is_basket_vault(empty)

    # Per-symbol-style vault (strategy.py present, no basket.yaml)
    per_sym = tmp_path / "PER_SYMBOL"
    per_sym.mkdir()
    (per_sym / "strategy.py").write_text("# pretend strategy.py\n", encoding="utf-8")
    (per_sym / "meta.json").write_text("{}", encoding="utf-8")
    assert not is_basket_vault(per_sym)

    # Basket vault
    payload = _sample_payload()
    base = write_basket_vault(tmp_path / "BASKET_HOLDER", payload)
    assert is_basket_vault(base)


def test_idempotent_overwrite(tmp_path: Path):
    """Re-writing the same basket vault path is idempotent — overwrites cleanly."""
    payload = _sample_payload()
    base = write_basket_vault(tmp_path, payload)
    # Mutate and re-write
    payload.harvested_total_usd = 999.99
    write_basket_vault(tmp_path, payload)
    restored = read_basket_vault(base)
    assert restored.harvested_total_usd == 999.99


def test_read_rejects_non_basket_dir(tmp_path: Path):
    per_sym = tmp_path / "PER_SYMBOL_FAKE"
    per_sym.mkdir()
    (per_sym / "strategy.py").write_text("noop\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a basket vault"):
        read_basket_vault(per_sym)


def test_basket_meta_json_schema(tmp_path: Path):
    """basket_meta.json contains the documented invariants."""
    payload = _sample_payload()
    base = write_basket_vault(tmp_path, payload)
    meta = json.loads((base / "basket_meta.json").read_text(encoding="utf-8"))
    assert meta["basket_id"] == "H2"
    assert meta["rule_name"] == "H2_v7_compression"
    assert meta["rule_version"] == 1
    assert meta["leg_count"] == 2
    assert sorted(meta["leg_symbols"]) == ["EURUSD", "USDJPY"]
    assert meta["trade_total"] == sum(len(t) for t in payload.leg_trades.values())
    assert meta["recycle_event_count"] == len(payload.recycle_events)


def test_basket_yaml_round_trip_preserves_directive(tmp_path: Path):
    payload = _sample_payload()
    base = write_basket_vault(tmp_path, payload)
    with open(base / "basket.yaml", encoding="utf-8") as f:
        directive_back = yaml.safe_load(f)
    assert directive_back == payload.directive
