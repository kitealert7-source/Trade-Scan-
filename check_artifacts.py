import json, pandas as pd
from pathlib import Path

for directive in ["06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P61", "08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P31"]:
    print(f"\n--- {directive} ---")
    deploy_root = Path("strategies") / directive / "deployable"
    for prof in ["CONSERVATIVE_V1", "DYNAMIC_V1", "FIXED_USD_V1"]:
        d = deploy_root / prof
        assert d.exists(), f"Missing profile dir: {d}"
        m = json.loads((d / "summary_metrics.json").read_text())
        diff = abs(m["final_equity"] - (m["starting_capital"] + m["realized_pnl"]))
        assert diff < 0.01, f"[{prof}] Equity math mismatch: diff={diff}"
        assert m["final_equity"] > 0, f"[{prof}] Final equity is zero or negative"
        eq = pd.read_csv(d / "equity_curve.csv")
        assert eq["equity"].min() > 0, f"[{prof}] Negative equity detected"
        tl = pd.read_csv(d / "deployable_trade_log.csv")
        assert len(tl) == m["total_accepted"], f"[{prof}] Trade log count mismatch"
        print(f"[{prof}] PASS: final_equity={m['final_equity']:,.2f}, accepted={m['total_accepted']}")

print("\nAll deployable artifact checks PASSED.")
