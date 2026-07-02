"""
Verify broker spec YAMLs against MT5 ground truth.
====================================================
Reads the MT5 extraction JSON produced by TS_Execution/tools/extract_symbol_specs.py
and cross-validates every calibration value in data_access/broker_specs/OctaFx/*.yaml.

Usage:
    python tools/verify_broker_specs.py                          # report only
    python tools/verify_broker_specs.py --patch                  # report + update YAMLs
    python tools/verify_broker_specs.py --mt5-json <path>        # custom JSON path

Output:
    Console report with PASS/FAIL/DRIFT per symbol.
    With --patch: updates YAMLs in-place (contract_size, calibration, status,
    mt5_trade_contract_size, pricing_units_per_lot).

Monetary model (single-monetary-model invariant, INVAR-005 phase 2, 2026-07-02):
    - `contract_size` / `mt5_trade_contract_size`: RAW MT5 metadata, immutable
      semantics (provenance + drift detection). Never a pricing input.
    - `pricing_units_per_lot`: the CANONICAL pricing field, derived here from
      the MT5 tick calibration via derive_pricing_units_per_lot(). All pricing
      paths consume only this field.
    - GENERATION-TIME GATE: every emitted YAML is self-validated with
      validate_monetary_consistency() BEFORE writing. An inconsistent or
      irreconcilable spec is REFUSED (never written) and the run exits 2.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.path_authority import ANTI_GRAVITY_DATA_ROOT, TS_EXECUTION as _TS_EXECUTION
from tools.capital.capital_broker_spec import (
    derive_pricing_units_per_lot,
    validate_monetary_consistency,
)
BROKER_SPECS_DIR = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"

# Canonical 2026-05-23+ location — written by DATA_INGRESS's daily post-hook
# (engines/ops/extract_broker_specs.py). Shared sibling-accessible path.
_NEW_MT5_JSON = ANTI_GRAVITY_DATA_ROOT / "SYSTEM_FACTORS" / "BROKER_SPECS" / "symbol_specs_mt5.json"
# Legacy location — TS_Execution/tools/extract_symbol_specs.py output, kept as
# fallback during the migration window so existing snapshots remain readable.
_LEGACY_MT5_JSON = _TS_EXECUTION / "outputs" / "symbol_specs_mt5.json"
# Prefer the new location if it exists; otherwise fall back to the legacy one.
DEFAULT_MT5_JSON = _NEW_MT5_JSON if _NEW_MT5_JSON.exists() else _LEGACY_MT5_JSON
import yaml


def load_mt5_data(mt5_path):
    """Load the MT5 extraction JSON."""
    with open(mt5_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_broker_spec(symbol):
    """Load a single broker spec YAML."""
    p = BROKER_SPECS_DIR / f"{symbol}.yaml"
    if not p.exists():
        return None, p
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f), p


def compare_symbol(symbol, mt5_spec, yaml_spec, force_all=False):
    """Compare MT5 ground truth against YAML spec. Returns findings dict.

    If force_all=True, always populate patch with MT5 values regardless of drift.
    """
    findings = {
        "symbol": symbol,
        "status": "PASS",
        "issues": [],
        "mt5": {},
        "yaml": {},
        "patch": {},
    }

    # --- contract_size ---
    mt5_cs = mt5_spec.get("trade_contract_size")
    yaml_cs = yaml_spec.get("contract_size")
    findings["mt5"]["contract_size"] = mt5_cs
    findings["yaml"]["contract_size"] = yaml_cs

    if mt5_cs is not None:
        if force_all:
            findings["patch"]["contract_size"] = mt5_cs
            if yaml_cs is not None and abs(float(mt5_cs) - float(yaml_cs)) > 0.01:
                findings["issues"].append(
                    f"contract_size: YAML={yaml_cs} vs MT5={mt5_cs}"
                )
                findings["status"] = "MISMATCH"
        elif yaml_cs is not None and abs(float(mt5_cs) - float(yaml_cs)) > 0.01:
            findings["issues"].append(
                f"contract_size: YAML={yaml_cs} vs MT5={mt5_cs}"
            )
            findings["patch"]["contract_size"] = mt5_cs
            findings["status"] = "MISMATCH"

    # --- calibration: usd_pnl_per_price_unit_0p01 ---
    mt5_derived = mt5_spec.get("derived_usd_pnl_per_pu_0p01")
    yaml_cal = yaml_spec.get("calibration", {})
    yaml_0p01 = yaml_cal.get("usd_pnl_per_price_unit_0p01")
    findings["mt5"]["usd_pnl_per_pu_0p01"] = mt5_derived
    findings["yaml"]["usd_pnl_per_pu_0p01"] = yaml_0p01

    if mt5_derived is not None:
        # Always patch to MT5 value in force mode
        if force_all:
            findings["patch"]["usd_pnl_per_pu_0p01"] = mt5_derived

        if yaml_0p01 is not None:
            ratio = float(yaml_0p01) / float(mt5_derived) if mt5_derived != 0 else float("inf")
            findings["mt5"]["ratio_yaml_over_mt5"] = round(ratio, 4)

            if abs(ratio - 1.0) > 0.15:
                findings["issues"].append(
                    f"usd_pnl_per_pu_0p01: YAML={yaml_0p01} vs MT5_derived={mt5_derived} "
                    f"(ratio={ratio:.4f}, >15% drift)"
                )
                findings["patch"]["usd_pnl_per_pu_0p01"] = mt5_derived
                findings["status"] = "DRIFT" if findings["status"] == "PASS" else findings["status"]
            elif abs(ratio - 1.0) > 0.05:
                findings["issues"].append(
                    f"usd_pnl_per_pu_0p01: minor drift YAML={yaml_0p01} vs MT5={mt5_derived} "
                    f"(ratio={ratio:.4f})"
                )
                if findings["status"] == "PASS":
                    findings["status"] = "MINOR_DRIFT"

    # --- volume_min / volume_step ---
    mt5_vmin = mt5_spec.get("volume_min")
    yaml_vmin = yaml_spec.get("min_lot") or yaml_spec.get("volume_min")
    if mt5_vmin is not None:
        if force_all:
            findings["patch"]["min_lot"] = mt5_vmin
        elif yaml_vmin is not None and abs(float(mt5_vmin) - float(yaml_vmin)) > 0.001:
            findings["issues"].append(f"volume_min: YAML={yaml_vmin} vs MT5={mt5_vmin}")
            findings["patch"]["min_lot"] = mt5_vmin

    mt5_vstep = mt5_spec.get("volume_step")
    yaml_vstep = yaml_spec.get("lot_step") or yaml_spec.get("volume_step")
    if mt5_vstep is not None:
        if force_all:
            findings["patch"]["lot_step"] = mt5_vstep
        elif yaml_vstep is not None and abs(float(mt5_vstep) - float(yaml_vstep)) > 0.001:
            findings["issues"].append(f"volume_step: YAML={yaml_vstep} vs MT5={mt5_vstep}")
            findings["patch"]["lot_step"] = mt5_vstep

    # --- volume_max ---
    mt5_vmax = mt5_spec.get("volume_max")
    if mt5_vmax is not None and force_all:
        findings["patch"]["max_lot"] = mt5_vmax

    # --- currency_profit ---
    mt5_ccy = mt5_spec.get("currency_profit", "")
    findings["mt5"]["currency_profit"] = mt5_ccy

    # --- tick details ---
    findings["mt5"]["tick_size"] = mt5_spec.get("trade_tick_size")
    findings["mt5"]["tick_value"] = mt5_spec.get("trade_tick_value")
    findings["mt5"]["digits"] = mt5_spec.get("digits")
    findings["mt5"]["usd_per_pu_per_lot"] = mt5_spec.get("derived_usd_per_pu_per_lot")

    # --- canonical pricing field (INVAR-005 phase 2) ---
    # Report-mode visibility: a missing or drifted pricing_units_per_lot is a
    # DRIFT (regeneration needed); an underivable one (MT5 metadata disagrees
    # with calibration AND profit ccy is not USD) is IRRECONCILABLE — the
    # patch phase will REFUSE to write such a spec.
    yaml_pu = yaml_spec.get("pricing_units_per_lot")
    findings["yaml"]["pricing_units_per_lot"] = yaml_pu
    mt5_upl = mt5_spec.get("derived_usd_per_pu_per_lot")
    if mt5_upl:
        try:
            expected_pu, basis = derive_pricing_units_per_lot(
                mt5_cs, float(mt5_upl), mt5_ccy or "USD")
            findings["mt5"]["expected_pricing_units_per_lot"] = expected_pu
            if (yaml_pu is None
                    or abs(float(yaml_pu) - expected_pu) > 1e-6 * expected_pu):
                findings["issues"].append(
                    f"pricing_units_per_lot: YAML={yaml_pu} vs "
                    f"derived={expected_pu} (basis={basis})"
                )
                findings["patch"]["pricing_units_per_lot"] = expected_pu
                if findings["status"] == "PASS":
                    findings["status"] = "DRIFT"
        except ValueError as exc:
            findings["issues"].append(f"pricing_units_per_lot IRRECONCILABLE: {exc}")
            findings["status"] = "IRRECONCILABLE"

    return findings


def patch_yaml(yaml_path, findings):
    """Apply patches to a YAML file in-place."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    patches_applied = []
    patch = findings["patch"]

    if "contract_size" in patch:
        old_val = data.get("contract_size")
        data["contract_size"] = patch["contract_size"]
        if old_val != patch["contract_size"]:
            patches_applied.append(f"contract_size: {old_val} -> {patch['contract_size']}")

    # NOTE: usd_pnl_per_price_unit_0p01 is intentionally NOT patched from the
    # MT5 `derived_usd_pnl_per_pu_0p01` field here. It is derived from
    # usd_per_pu_per_lot below (invariant: == usd_per_pu_per_lot * 0.01, same as
    # create_yaml_from_mt5 and relied on by capital_wrapper / simulation).
    # Patching it from a separate MT5 field on a different (>15%-drift) cadence
    # than usd_per_pu_per_lot was the cause of sibling-field drift between them.

    if "min_lot" in patch:
        old_val = data.get("min_lot")
        data["min_lot"] = patch["min_lot"]
        if old_val != patch["min_lot"]:
            patches_applied.append(f"min_lot: {old_val} -> {patch['min_lot']}")

    if "lot_step" in patch:
        old_val = data.get("lot_step")
        data["lot_step"] = patch["lot_step"]
        if old_val != patch["lot_step"]:
            patches_applied.append(f"lot_step: {old_val} -> {patch['lot_step']}")

    if "max_lot" in patch:
        old_val = data.get("max_lot")
        data["max_lot"] = patch["max_lot"]
        if old_val != patch["max_lot"]:
            patches_applied.append(f"max_lot: {old_val} -> {patch['max_lot']}")

    # Update calibration status
    if "calibration" not in data:
        data["calibration"] = {}
    old_status = data["calibration"].get("status", "UNKNOWN")
    data["calibration"]["status"] = "MT5_VERIFIED"
    if old_status != "MT5_VERIFIED":
        patches_applied.append(f"calibration.status: {old_status} -> MT5_VERIFIED")

    # Add currency_profit from MT5 (quote currency for the instrument)
    mt5_ccy = findings["mt5"].get("currency_profit")
    if mt5_ccy:
        old_ccy = data["calibration"].get("currency_profit")
        data["calibration"]["currency_profit"] = mt5_ccy
        if old_ccy != mt5_ccy:
            patches_applied.append(f"calibration.currency_profit: {old_ccy} -> {mt5_ccy}")

    # Add MT5 tick details for reference
    mt5_tick_val = findings["mt5"].get("tick_value")
    mt5_tick_size = findings["mt5"].get("tick_size")
    mt5_usd_per_pu = findings["mt5"].get("usd_per_pu_per_lot")
    if mt5_tick_val is not None:
        data["calibration"]["mt5_tick_value"] = mt5_tick_val
    if mt5_tick_size is not None:
        data["calibration"]["mt5_tick_size"] = mt5_tick_size
    if mt5_usd_per_pu is not None:
        data["calibration"]["usd_per_pu_per_lot"] = mt5_usd_per_pu
        patches_applied.append(f"calibration.usd_per_pu_per_lot: {mt5_usd_per_pu}")
        # Enforce invariant: usd_pnl_per_price_unit_0p01 == usd_per_pu_per_lot * 0.01
        # (matches create_yaml_from_mt5; relied on by capital_wrapper / simulation).
        derived_0p01 = round(float(mt5_usd_per_pu) * 0.01, 6)
        old_0p01 = data["calibration"].get("usd_pnl_per_price_unit_0p01")
        data["calibration"]["usd_pnl_per_price_unit_0p01"] = derived_0p01
        if old_0p01 != derived_0p01:
            patches_applied.append(
                f"calibration.usd_pnl_per_price_unit_0p01: {old_0p01} -> {derived_0p01}"
            )

    # Add digits from MT5
    mt5_digits = findings["mt5"].get("digits")
    if mt5_digits is not None:
        data["calibration"]["digits"] = mt5_digits

    # ── Canonical pricing field (INVAR-005 phase 2, 2026-07-02) ──────────
    # 1. mt5_trade_contract_size: raw MT5 provenance, always persisted.
    #    (contract_size above keeps tracking the same raw MT5 value — its
    #    semantics are immutable; it is metadata, never a pricing input.)
    raw_cs = findings["mt5"].get("contract_size")
    if raw_cs is not None:
        old_raw = data.get("mt5_trade_contract_size")
        data["mt5_trade_contract_size"] = raw_cs
        if old_raw != raw_cs:
            patches_applied.append(f"mt5_trade_contract_size: {old_raw} -> {raw_cs}")

    # 2. pricing_units_per_lot: derived from the FINAL patched state (not the
    #    pre-patch findings), so the emitted file is internally consistent by
    #    construction. derive_pricing_units_per_lot raises ValueError on an
    #    irreconcilable spec — propagated to the caller, which REFUSES the
    #    write (generation-time gate: no inconsistent YAML is ever emitted).
    cal_upl = (data.get("calibration") or {}).get("usd_per_pu_per_lot")
    if cal_upl:
        profit_ccy = (data.get("calibration") or {}).get("currency_profit", "USD")
        pricing_units, basis = derive_pricing_units_per_lot(
            data.get("contract_size"), float(cal_upl), profit_ccy)
        old_pu = data.get("pricing_units_per_lot")
        data["pricing_units_per_lot"] = pricing_units
        if old_pu != pricing_units:
            patches_applied.append(
                f"pricing_units_per_lot: {old_pu} -> {pricing_units} (basis={basis})")

    # 3. Self-validate the fully patched spec BEFORE writing. Raises
    #    ValueError on inconsistency — the caller refuses the write.
    _sym = findings.get("symbol") or data.get("symbol") or yaml_path.stem
    validate_monetary_consistency(data, _sym)

    # Write back
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return patches_applied


def create_yaml_from_mt5(symbol, mt5_spec):
    """Create a new broker spec YAML from MT5 ground truth.

    Applies the same generation-time gate as patch_yaml: the canonical
    pricing_units_per_lot is derived from the calibration, and the assembled
    spec is self-validated BEFORE writing. Raises ValueError (spec refused,
    nothing written) if the MT5 metadata is irreconcilable with the tick
    calibration.
    """
    tick_size = mt5_spec.get("trade_tick_size", 0)
    tick_value = mt5_spec.get("trade_tick_value", 0)
    usd_per_pu_per_lot = tick_value / tick_size if tick_size > 0 else 0
    usd_pnl_per_pu_0p01 = usd_per_pu_per_lot * 0.01

    raw_cs = mt5_spec.get("trade_contract_size")
    profit_ccy = mt5_spec.get("currency_profit", "USD")

    data = {
        "broker": "OctaFX",
        "reference_capital_usd": 1000,
        "symbol": symbol,
        "min_lot": mt5_spec.get("volume_min", 0.01),
        "lot_step": mt5_spec.get("volume_step", 0.01),
        "max_lot": mt5_spec.get("volume_max", 100.0),
        "cost_model": "embedded",
        "apply_additional_costs": False,
        "infer_missing_fields": False,
        "allow_manual_override": False,
        "contract_size": raw_cs,
        "mt5_trade_contract_size": raw_cs,
        "calibration": {
            "base_lot": 0.01,
            "usd_pnl_per_price_unit_0p01": round(usd_pnl_per_pu_0p01, 6),
            "usd_per_pu_per_lot": round(usd_per_pu_per_lot, 6),
            "currency_profit": profit_ccy,
            "mt5_tick_value": tick_value,
            "mt5_tick_size": tick_size,
            "digits": mt5_spec.get("digits"),
            "status": "MT5_VERIFIED",
        },
    }

    # Canonical pricing field + generation-time gate (raises on refusal).
    if usd_per_pu_per_lot > 0:
        pricing_units, _basis = derive_pricing_units_per_lot(
            raw_cs, round(usd_per_pu_per_lot, 6), profit_ccy)
        data["pricing_units_per_lot"] = pricing_units
    validate_monetary_consistency(data, symbol)

    yaml_path = BROKER_SPECS_DIR / f"{symbol}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="Verify broker specs against MT5 ground truth")
    parser.add_argument("--mt5-json", type=str, default=str(DEFAULT_MT5_JSON),
                        help="Path to symbol_specs_mt5.json")
    parser.add_argument("--patch", action="store_true",
                        help="Apply corrections to YAML files")
    parser.add_argument("--force-all", action="store_true",
                        help="Force-patch ALL symbols to MT5 values (not just drifted ones)")
    parser.add_argument("--target-dir", type=str, default=None,
                        help="Override broker_specs YAMLs directory. Default: Trade_Scan local "
                             "(data_access/broker_specs/OctaFx). The DATA_INGRESS pipeline wrapper "
                             "passes the canonical DATA_INGRESS path here so the patch writes to "
                             "the new source-of-truth location (2026-05-25 migration).")
    args = parser.parse_args()

    if args.target_dir:
        # Override module-global so all downstream functions see the new dir.
        # Explicit cross-repo path via CLI is intentional — keeps the coupling
        # visible at orchestration time instead of hiding it in script defaults.
        global BROKER_SPECS_DIR
        BROKER_SPECS_DIR = Path(args.target_dir)
        if not BROKER_SPECS_DIR.exists() or not BROKER_SPECS_DIR.is_dir():
            print(f"ERROR: --target-dir does not exist or is not a directory: {BROKER_SPECS_DIR}")
            sys.exit(1)

    mt5_path = Path(args.mt5_json)
    if not mt5_path.exists():
        print(f"ERROR: MT5 JSON not found at {mt5_path}")
        print(f"Run TS_Execution/tools/extract_symbol_specs.py first.")
        sys.exit(1)

    print("=" * 100)
    print("BROKER SPEC VERIFICATION — MT5 GROUND TRUTH")
    print("=" * 100)

    # Load MT5 data
    mt5_data = load_mt5_data(mt5_path)
    print(f"\nMT5 extraction date: {mt5_data.get('extraction_date', 'unknown')}")
    print(f"Account currency: {mt5_data.get('account_currency', 'unknown')}")
    mt5_symbols = mt5_data.get("symbols", {})
    print(f"MT5 symbols: {len(mt5_symbols)}")

    # Process each broker spec
    all_findings = []
    counters = {"PASS": 0, "MINOR_DRIFT": 0, "DRIFT": 0, "MISMATCH": 0,
                "IRRECONCILABLE": 0, "NO_MT5": 0, "NO_YAML": 0}
    refused = []  # symbols whose YAML write was REFUSED by the generation gate

    # Get all symbols (union of MT5 + YAML)
    yaml_symbols = {f.stem for f in BROKER_SPECS_DIR.glob("*.yaml")}
    all_symbols = sorted(yaml_symbols | set(mt5_symbols.keys()))

    print(f"\n{'Symbol':<12} {'Status':<14} {'Profit$':<8} {'CS':>8} {'YAML_0p01':>12} "
          f"{'MT5_0p01':>12} {'Ratio':>8} {'Issues'}")
    print("-" * 110)

    for sym in all_symbols:
        mt5_spec = mt5_symbols.get(sym)
        yaml_spec, yaml_path = load_broker_spec(sym)

        if mt5_spec is None:
            print(f"  {sym:<12} {'NO_MT5':<14}")
            counters["NO_MT5"] += 1
            continue

        if yaml_spec is None:
            if args.patch or args.force_all:
                # Create new YAML from MT5 ground truth (gate may refuse)
                try:
                    created_path = create_yaml_from_mt5(sym, mt5_spec)
                    print(f"  {sym:<12} {'CREATED':<14}  -> {created_path.name}")
                except ValueError as exc:
                    refused.append(sym)
                    print(f"  {sym:<12} {'REFUSED':<14}  generation gate: {exc}")
                counters["NO_YAML"] += 1
                continue
            else:
                print(f"  {sym:<12} {'NO_YAML':<14}  (MT5 has it, YAML missing)")
                counters["NO_YAML"] += 1
                continue

        findings = compare_symbol(sym, mt5_spec, yaml_spec, force_all=args.force_all)
        all_findings.append(findings)
        counters[findings["status"]] += 1

        # Print row
        mt5_ccy = mt5_spec.get("currency_profit", "?")
        mt5_cs = mt5_spec.get("trade_contract_size", "?")
        yaml_0p01 = findings["yaml"].get("usd_pnl_per_pu_0p01", "?")
        mt5_0p01 = findings["mt5"].get("usd_pnl_per_pu_0p01", "?")
        ratio = findings["mt5"].get("ratio_yaml_over_mt5", "")
        ratio_str = f"{ratio:.4f}" if isinstance(ratio, float) else ""
        issues_str = "; ".join(findings["issues"][:2]) if findings["issues"] else ""

        status = findings["status"]
        flag = ""
        if status == "MISMATCH":
            flag = " ***"
        elif status == "DRIFT":
            flag = " **"
        elif status == "MINOR_DRIFT":
            flag = " *"

        print(f"  {sym:<12} {status + flag:<14} {mt5_ccy:<8} {str(mt5_cs):>8} "
              f"{str(yaml_0p01):>12} {str(mt5_0p01):>12} {ratio_str:>8} {issues_str}")

    # Summary
    print(f"\n{'=' * 100}")
    print("SUMMARY")
    print(f"{'=' * 100}")
    for status, count in sorted(counters.items()):
        if count > 0:
            print(f"  {status:<14} {count}")

    # Patch if requested
    if args.patch or args.force_all:
        print(f"\n{'=' * 100}")
        mode = "FORCE-PATCHING ALL" if args.force_all else "PATCHING"
        print(f"{mode} YAML FILES")
        print(f"{'=' * 100}")

        patched = 0
        for findings in all_findings:
            sym = findings["symbol"]
            _, yaml_path = load_broker_spec(sym)
            if yaml_path is None or not yaml_path.exists():
                continue

            try:
                patches = patch_yaml(yaml_path, findings)
            except ValueError as exc:
                # Generation-time gate: the patched spec failed monetary
                # self-validation — the YAML on disk was NOT modified.
                refused.append(sym)
                print(f"\n  {sym}: REFUSED (spec not written)")
                print(f"    {exc}")
                continue
            if patches:
                patched += 1
                print(f"\n  {sym}:")
                for p in patches:
                    print(f"    {p}")
            elif args.force_all:
                # Even if no visible changes, still count as verified
                print(f"\n  {sym}: (already at MT5 values)")

        print(f"\n  Patched {patched} files.")
        if refused:
            print(f"\n  REFUSED {len(refused)} spec(s) at the generation gate: "
                  f"{', '.join(refused)}")
            print("  These YAMLs were NOT written. Operator review required "
                  "(irreconcilable MT5 metadata vs tick calibration).")
    else:
        needs_patch = sum(1 for f in all_findings if f["issues"])
        if needs_patch:
            print(f"\n  {needs_patch} symbols have issues. Run with --patch or --force-all to fix.")

    print("\nDone.")
    if refused:
        sys.exit(2)


if __name__ == "__main__":
    main()
