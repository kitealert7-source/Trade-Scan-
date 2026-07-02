"""Single-monetary-model invariant — INVAR-005 phase 2 (2026-07-02).

Locks the canonical-pricing-field architecture:

  - `calibration.usd_per_pu_per_lot` (MT5 tick-derived) is the ONLY monetary
    authority.
  - `pricing_units_per_lot` is its persisted representation, derived at
    generation time (verify_broker_specs.py --patch) via
    derive_pricing_units_per_lot().
  - `contract_size` / `mt5_trade_contract_size` are RAW MT5 metadata —
    immutable semantics, never a pricing input.
  - The generator REFUSES to emit an inconsistent YAML (generation-time gate).
  - validate_monetary_consistency() checks the persisted representation
    against the calibration authority — never two authorities against each
    other — with a byte-identical legacy fallback for un-regenerated specs.
  - Stage-1 (tools/run_stage1.py) prices exclusively from
    pricing_units_per_lot (AST-guarded below).

Root incident: OctaFX MT5 reports trade_contract_size=10 for SPX500 while the
tick calibration proves $1/pt/lot -> 6 FSP rows carried 10x-inflated dollars.
"""

import ast
import copy
from pathlib import Path

import pytest
import yaml

from tools.capital.capital_broker_spec import (
    derive_pricing_units_per_lot,
    validate_monetary_consistency,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROKER_SPECS_DIR = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
RUN_STAGE1 = PROJECT_ROOT / "tools" / "run_stage1.py"


# ======================================================================
# 1. Derivation — honest passthrough / USD quirk / refusals
# ======================================================================

class TestDerivePricingUnitsPerLot:
    # Real-world corpus values (MT5-verified 2026-07-02).
    HONEST_CASES = [
        # (symbol, contract_size, usd_per_pu_per_lot, profit_ccy)
        ("EURUSD-like",  100000.0, 100000.0,  "USD"),
        ("XAUUSD-like",  100.0,    100.0,     "USD"),
        ("US30-like",    10.0,     10.0,      "USD"),
        ("NAS100-like",  10.0,     10.0,      "USD"),
        ("GER40-like",   10.0,     11.3814,   "EUR"),
        ("JPN225-like",  100.0,    0.615176,  "JPY"),
        ("UK100-like",   10.0,     13.28240,  "GBP"),
        ("USDCAD-like",  100000.0, 70343.2752, "CAD"),
    ]

    @pytest.mark.parametrize("name,cs,upl,ccy", HONEST_CASES)
    def test_honest_symbol_passes_through_contract_size(self, name, cs, upl, ccy):
        """Honest MT5 metadata -> pricing_units_per_lot == contract_size.

        This IS the Stage-1 parity guarantee: units = lots * value is
        numerically unchanged for every honest symbol.
        """
        value, basis = derive_pricing_units_per_lot(cs, upl, ccy)
        assert value == cs
        assert basis == "MT5_CONTRACT_SIZE"

    def test_usd_quirk_reconciles_to_calibration(self):
        """The SPX500 case: metadata 10 vs calibrated $1/pt/lot -> 1.0 exact."""
        value, basis = derive_pricing_units_per_lot(10.0, 1.0, "USD")
        assert value == 1.0
        assert basis == "CALIBRATION_USD"

    def test_non_usd_quirk_refuses(self):
        """A quirky non-USD symbol cannot be backed out without an FX rate."""
        with pytest.raises(ValueError, match="refusing to guess"):
            derive_pricing_units_per_lot(10.0, 1.0, "EUR")

    def test_unknown_profit_ccy_refuses(self):
        with pytest.raises(ValueError, match="no FX plausibility band"):
            derive_pricing_units_per_lot(100.0, 100.0, "XXX")

    def test_missing_contract_size_usd_uses_calibration(self):
        value, basis = derive_pricing_units_per_lot(None, 42.0, "USD")
        assert value == 42.0
        assert basis == "CALIBRATION_USD"

    def test_missing_contract_size_non_usd_refuses(self):
        with pytest.raises(ValueError):
            derive_pricing_units_per_lot(None, 42.0, "EUR")


# ======================================================================
# 2. Runtime gate — persisted representation vs calibration authority
# ======================================================================

def _spec(pricing_units=None, contract_size=None, upl_0p01=None, ccy="USD"):
    s = {"symbol": "TEST"}
    if contract_size is not None:
        s["contract_size"] = contract_size
    if pricing_units is not None:
        s["pricing_units_per_lot"] = pricing_units
    if upl_0p01 is not None:
        s["calibration"] = {
            "usd_pnl_per_price_unit_0p01": upl_0p01,
            "currency_profit": ccy,
        }
    return s


class TestValidateMonetaryConsistency:
    def test_reconciled_usd_spec_passes(self):
        # SPX500 end-state: raw metadata 10, persisted pricing field 1.0.
        validate_monetary_consistency(
            _spec(pricing_units=1.0, contract_size=10.0, upl_0p01=0.01), "SPX500")

    def test_usd_pricing_field_must_match_calibration_exactly(self):
        # pricing field parroting the raw metadata (10) while the calibration
        # says $1/pt/lot -> REFUSED. The gate validates the persisted
        # representation against the authority, never metadata vs metadata.
        with pytest.raises(ValueError, match="strict equality"):
            validate_monetary_consistency(
                _spec(pricing_units=10.0, contract_size=10.0, upl_0p01=0.01),
                "SPX500")

    def test_non_usd_pricing_field_band_pass(self):
        # GER40: pricing 10, calibrated 11.3814 USD/pt/lot -> EUR band.
        validate_monetary_consistency(
            _spec(pricing_units=10.0, contract_size=10.0, upl_0p01=0.113814,
                  ccy="EUR"), "GER40")

    def test_non_usd_pricing_field_band_fail(self):
        with pytest.raises(ValueError, match="inconsistent"):
            validate_monetary_consistency(
                _spec(pricing_units=100.0, contract_size=100.0,
                      upl_0p01=0.113814, ccy="EUR"), "GER40")

    def test_nonpositive_pricing_field_refused(self):
        with pytest.raises(ValueError, match="not a positive number"):
            validate_monetary_consistency(
                _spec(pricing_units=0.0, upl_0p01=0.01), "TEST")

    def test_legacy_fallback_quirky_spec_still_refuses(self):
        # Un-regenerated SPX500 (no pricing field, metadata 10 vs $1/pt/lot)
        # keeps refusing exactly as the original 2026-07-02 gate did.
        with pytest.raises(ValueError, match="inconsistent"):
            validate_monetary_consistency(
                _spec(contract_size=10.0, upl_0p01=0.01), "SPX500")

    def test_legacy_fallback_honest_spec_passes(self):
        validate_monetary_consistency(
            _spec(contract_size=10.0, upl_0p01=0.1), "US30")

    def test_no_calibration_passes_through(self):
        validate_monetary_consistency(
            _spec(contract_size=100000.0), "LEGACY_NO_CAL")


# ======================================================================
# 3. Corpus — every real spec on disk passes the gate
# ======================================================================

def test_local_spec_corpus_passes_gate():
    yamls = sorted(BROKER_SPECS_DIR.glob("*.yaml"))
    assert yamls, f"No broker specs found in {BROKER_SPECS_DIR}"
    failures = []
    for p in yamls:
        with open(p, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        try:
            validate_monetary_consistency(spec, p.stem)
        except ValueError as exc:
            failures.append(f"{p.stem}: {exc}")
    assert not failures, (
        "Broker specs failing the monetary gate (regenerate with "
        "verify_broker_specs.py --patch):\n" + "\n".join(failures))


# ======================================================================
# 4. Generator — patch/create never emit an inconsistent YAML
# ======================================================================

def _quirky_spx_yaml(tmp_path):
    """A stale SPX500-like spec as it existed pre-fix (metadata=pricing)."""
    data = {
        "broker": "OctaFX", "symbol": "SPX500",
        "min_lot": 0.01, "lot_step": 0.01, "max_lot": 500.0,
        "contract_size": 10.0,
        "calibration": {
            "base_lot": 0.01,
            "usd_pnl_per_price_unit_0p01": 0.01,
            "usd_per_pu_per_lot": 1.0,
            "currency_profit": "USD",
            "status": "MT5_VERIFIED",
        },
    }
    p = tmp_path / "SPX500.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)
    return p


def _findings(symbol, mt5_cs, upl, ccy, tick_value=None, tick_size=None):
    return {
        "symbol": symbol, "status": "PASS", "issues": [], "yaml": {},
        "patch": {},
        "mt5": {
            "contract_size": mt5_cs,
            "currency_profit": ccy,
            "tick_value": tick_value,
            "tick_size": tick_size,
            "usd_per_pu_per_lot": upl,
            "digits": 1,
        },
    }


class TestGeneratorGate:
    def test_patch_reconciles_usd_quirk(self, tmp_path):
        from tools.verify_broker_specs import patch_yaml
        p = _quirky_spx_yaml(tmp_path)
        patches = patch_yaml(p, _findings("SPX500", 10.0, 1.0, "USD"))
        with open(p, encoding="utf-8") as f:
            out = yaml.safe_load(f)
        # contract_size immutable at raw MT5 semantics; provenance persisted;
        # canonical field reconciled to the calibration authority.
        assert out["contract_size"] == 10.0
        assert out["mt5_trade_contract_size"] == 10.0
        assert out["pricing_units_per_lot"] == 1.0
        validate_monetary_consistency(out, "SPX500")  # emitted spec is consistent
        assert any("pricing_units_per_lot" in x for x in patches)

    def test_patch_refuses_irreconcilable_and_leaves_file_untouched(self, tmp_path):
        from tools.verify_broker_specs import patch_yaml
        p = _quirky_spx_yaml(tmp_path)
        # Rewrite as a non-USD quirk: calibration disagrees, EUR profit ccy.
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["calibration"]["currency_profit"] = "EUR"
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False)
        before = p.read_bytes()

        with pytest.raises(ValueError):
            patch_yaml(p, _findings("SPX500", 10.0, 1.0, "EUR"))
        assert p.read_bytes() == before, "REFUSED patch must not modify the YAML"

    def test_create_yaml_emits_consistent_spec(self, tmp_path, monkeypatch):
        import tools.verify_broker_specs as vbs
        monkeypatch.setattr(vbs, "BROKER_SPECS_DIR", tmp_path)
        mt5_spec = {
            "trade_contract_size": 10.0,
            "trade_tick_size": 0.1, "trade_tick_value": 0.1,  # -> $1/pt/lot
            "currency_profit": "USD",
            "volume_min": 0.01, "volume_step": 0.01, "volume_max": 500.0,
            "digits": 1,
        }
        path = vbs.create_yaml_from_mt5("SPX500", mt5_spec)
        with open(path, encoding="utf-8") as f:
            out = yaml.safe_load(f)
        assert out["pricing_units_per_lot"] == 1.0
        assert out["mt5_trade_contract_size"] == 10.0
        assert out["contract_size"] == 10.0
        validate_monetary_consistency(out, "SPX500")

    def test_create_yaml_refuses_irreconcilable(self, tmp_path, monkeypatch):
        import tools.verify_broker_specs as vbs
        monkeypatch.setattr(vbs, "BROKER_SPECS_DIR", tmp_path)
        mt5_spec = {
            "trade_contract_size": 10.0,
            "trade_tick_size": 0.1, "trade_tick_value": 0.1,
            "currency_profit": "EUR",  # non-USD quirk -> refuse
            "volume_min": 0.01, "volume_step": 0.01, "volume_max": 500.0,
            "digits": 1,
        }
        with pytest.raises(ValueError):
            vbs.create_yaml_from_mt5("QUIRK", mt5_spec)
        assert not (tmp_path / "QUIRK.yaml").exists(), \
            "REFUSED creation must not write a YAML"


# ======================================================================
# 5. Stage-1 strictness — actionable remediation on legacy specs
# ======================================================================

def test_stage1_missing_pricing_field_error_is_actionable(tmp_path, monkeypatch):
    import tools.run_stage1 as rs1
    specs = tmp_path / "data_access" / "broker_specs" / "OctaFx"
    specs.mkdir(parents=True)
    legacy = {"symbol": "OLDSYM", "contract_size": 100000.0, "min_lot": 0.01}
    with open(specs / "OLDSYM.yaml", "w", encoding="utf-8") as f:
        yaml.dump(legacy, f)
    monkeypatch.setattr(rs1, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError) as exc_info:
        rs1.load_broker_spec("OLDSYM")
    msg = str(exc_info.value)
    assert "pricing_units_per_lot" in msg
    assert "verify_broker_specs.py --patch" in msg  # remediation named


# ======================================================================
# 6. Architectural guard — no pricing path consumes contract_size
# ======================================================================

def _string_key_accesses(tree):
    """All string keys accessed via subscript (d["k"]) or .get("k")."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.add(sl.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    keys.add(node.args[0].value)
    return keys


def test_stage1_pricing_path_never_reads_contract_size():
    """ARCHITECTURAL GUARD (INVAR-005 phase 2).

    tools/run_stage1.py must not read `contract_size` (subscript or .get) —
    Stage-1 prices exclusively from the canonical `pricing_units_per_lot`.
    If this test fails, someone has reintroduced the raw MT5 metadata field
    into the Stage-1 pricing path: the exact defect that produced the SPX500
    10x dollar inflation. Consume `pricing_units_per_lot` instead.
    """
    tree = ast.parse(RUN_STAGE1.read_text(encoding="utf-8"))
    accessed = _string_key_accesses(tree)
    assert "contract_size" not in accessed, (
        "tools/run_stage1.py reads 'contract_size' — the Stage-1 pricing path "
        "must consume only 'pricing_units_per_lot' (single-monetary-model "
        "invariant INVAR-005). Raw MT5 contract_size is metadata, not a "
        "pricing input.")
    assert "pricing_units_per_lot" in accessed, (
        "tools/run_stage1.py no longer reads 'pricing_units_per_lot' — the "
        "canonical pricing field has been dropped from the Stage-1 path.")
