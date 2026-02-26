"""
USDCHF Isolation Analysis — AK36_FX_PORTABILITY_4H / CONSERVATIVE_V1
One-shot script: filters to USDCHF only, runs all requested sections.
"""
import sys, json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from tools.utils.research import simulators, robustness, rolling, drawdown, friction

PREFIX = "AK36_FX_PORTABILITY_4H"
PROFILE = "CONSERVATIVE_V1"
SYMBOL = "USDCHF"

# ── Load deployable artifacts, filter to USDCHF ──
deploy = PROJECT_ROOT / "strategies" / PREFIX / "deployable" / PROFILE
tr_all = pd.read_csv(deploy / "deployable_trade_log.csv")
eq_all = pd.read_csv(deploy / "equity_curve.csv")
with open(deploy / "summary_metrics.json") as f:
    metrics = json.load(f)

tr_df = tr_all[tr_all["symbol"].str.contains(SYMBOL)].reset_index(drop=True)
start_cap = metrics["starting_capital"]

# ── Load fixed-lot (raw Stage-1) data ──
raw_dir = PROJECT_ROOT / "backtests" / f"{PREFIX}_{SYMBOL}" / "raw"
raw_tl = pd.read_csv(raw_dir / "results_tradelevel.csv") if (raw_dir / "results_tradelevel.csv").exists() else None

out = []
out.append(f"# USDCHF ISOLATION ANALYSIS — {PREFIX} / {PROFILE}\n")
out.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
out.append(f"Symbol: **{SYMBOL}** only | Deployable trades: **{len(tr_df)}**\n")

# ═══════════════════════════════════════════════════════════════
# SECTION 1 — Fixed-Lot Stats
# ═══════════════════════════════════════════════════════════════
out.append("## 1. Fixed-Lot Stats (Raw Stage-1)\n")
if raw_tl is not None:
    r = raw_tl
    pnl = r["pnl_usd"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gp = wins.sum() if len(wins) else 0
    gl = abs(losses.sum()) if len(losses) else 0
    pf_raw = gp / gl if gl > 0 else 999

    out.append(f"- Trades: {len(r)}")
    out.append(f"- PF: {pf_raw:.2f}")
    out.append(f"- Net PnL: ${pnl.sum():,.2f}")
    out.append(f"- Win Rate: {(pnl > 0).mean() * 100:.1f}%\n")

    # Year-wise
    out.append("### Year-Wise PnL (Fixed-Lot)\n")
    r2 = r.copy()
    r2["exit_timestamp"] = pd.to_datetime(r2["exit_timestamp"])
    r2["year"] = r2["exit_timestamp"].dt.year
    out.append("| Year | Trades | Net PnL | Win Rate |")
    out.append("|---|---|---|---|")
    for yr, grp in r2.groupby("year"):
        n = len(grp)
        net = grp["pnl_usd"].sum()
        wr = (grp["pnl_usd"] > 0).mean() * 100
        out.append(f"| {yr} | {n} | ${net:,.2f} | {wr:.1f}% |")
    out.append("")

    # Rolling 1Y on raw data (simple)
    out.append("### Rolling 1Y (Fixed-Lot)\n")
    r2 = r2.sort_values("exit_timestamp")
    r2["cum_pnl"] = r2["pnl_usd"].cumsum()
    r2_idx = r2.set_index("exit_timestamp")
    r2_roll = r2_idx["pnl_usd"].resample("D").sum().fillna(0)
    roll_1y = r2_roll.rolling(365).sum()
    neg_windows = (roll_1y.dropna() < 0).sum()
    total_windows = roll_1y.dropna().shape[0]
    out.append(f"- Total daily rolling windows: {total_windows}")
    out.append(f"- Negative windows: {neg_windows} ({neg_windows/total_windows*100:.1f}%)")
    out.append(f"- Worst 1Y PnL: ${roll_1y.min():,.2f}")
    out.append(f"- Best 1Y PnL: ${roll_1y.max():,.2f}")
    out.append(f"- Mean 1Y PnL: ${roll_1y.mean():,.2f}\n")

    # Regime Breakdown
    out.append("### Regime Breakdown (Fixed-Lot)\n")
    if "volatility_regime" in r.columns:
        out.append("**Volatility Regime:**\n")
        out.append("| Regime | Trades | Net PnL | PF |")
        out.append("|---|---|---|---|")
        for regime, grp in r.groupby("volatility_regime"):
            gw = grp["pnl_usd"][grp["pnl_usd"] > 0].sum()
            gli = abs(grp["pnl_usd"][grp["pnl_usd"] < 0].sum())
            pf_r = gw / gli if gli > 0 else 999
            out.append(f"| {regime} | {len(grp)} | ${grp['pnl_usd'].sum():,.2f} | {pf_r:.2f} |")
        out.append("")

    if "trend_label" in r.columns:
        out.append("**Trend Regime:**\n")
        out.append("| Regime | Trades | Net PnL | PF |")
        out.append("|---|---|---|---|")
        for regime, grp in r.groupby("trend_label"):
            gw = grp["pnl_usd"][grp["pnl_usd"] > 0].sum()
            gli = abs(grp["pnl_usd"][grp["pnl_usd"] < 0].sum())
            pf_r = gw / gli if gli > 0 else 999
            out.append(f"| {regime} | {len(grp)} | ${grp['pnl_usd'].sum():,.2f} | {pf_r:.2f} |")
        out.append("")
else:
    out.append("- [SKIPPED] Raw Stage-1 data not found.\n")

# ═══════════════════════════════════════════════════════════════
# SECTION 2 — Deployable Stats
# ═══════════════════════════════════════════════════════════════
out.append("## 2. Deployable Stats (Position-Sized)\n")
path = simulators.simulate_percent_path(tr_df, start_cap)
final_eq = path["final_equity"]
max_dd = path["max_dd_pct"]
cagr = path["cagr"] * 100

net = tr_df["pnl_usd"].sum()
max_dd_usd = max_dd / 100 * start_cap
recovery = net / max_dd_usd if max_dd_usd > 0 else 999

out.append(f"- CAGR: {cagr:.2f}%")
out.append(f"- Final Equity: ${final_eq:,.2f}")
out.append(f"- Max DD: {max_dd:.2f}%")
out.append(f"- Recovery Factor: {recovery:.2f}\n")

# Rolling 1Y DD on deployable
out.append("### Rolling 1Y DD (Deployable)\n")
tr_tmp2 = tr_df.copy()
tr_tmp2["exit_timestamp"] = pd.to_datetime(tr_tmp2["exit_timestamp"])
tr_tmp2 = tr_tmp2.sort_values("exit_timestamp")
tr_tmp2["cum_pnl"] = tr_tmp2["pnl_usd"].cumsum()
eq_series = start_cap + tr_tmp2.set_index("exit_timestamp")["cum_pnl"].resample("D").last().ffill()
if eq_series.notna().sum() > 365:
    peak_roll = eq_series.rolling(365, min_periods=1).max()
    dd_roll = (peak_roll - eq_series) / peak_roll * 100
    out.append(f"- Worst rolling 1Y DD: {dd_roll.max():.2f}%")
    out.append(f"- Mean rolling 1Y DD: {dd_roll.mean():.2f}%")
    neg_eq = (eq_series.rolling(365).apply(lambda x: x.iloc[-1] - x.iloc[0]).dropna() < 0).sum()
    out.append(f"- Negative 1Y return windows: {neg_eq}\n")

# ═══════════════════════════════════════════════════════════════
# SECTION 3 — Tail Contribution
# ═══════════════════════════════════════════════════════════════
out.append("## 3. Tail Contribution\n")
tc = robustness.tail_contribution(tr_df)
out.append(f"- Top 1 trade: {tc['top_1']:.2%}")
out.append(f"- Top 5 trades: {tc['top_5']:.2%}")
out.append(f"- Top 1% ({tc['n_1pct']}): {tc['top_1pct']:.2%}")
out.append(f"- Total PnL: ${tc['total_pnl']:,.2f}\n")

# ═══════════════════════════════════════════════════════════════
# SECTION 4 — Friction Stress
# ═══════════════════════════════════════════════════════════════
out.append("## 4. Friction Stress Test\n")
results = friction.run_friction_scenarios(tr_df)
out.append("| Scenario | Net Profit | PF | Degradation |")
out.append("|---|---|---|---|")
for r in results:
    out.append(f"| {r['scenario']} | ${r['net_profit']:,.2f} | {r['pf']:.2f} | {r['degradation_pct']:.2f}% |")
out.append("")

# ═══════════════════════════════════════════════════════════════
# SECTION 5 — Block Bootstrap (100 runs)
# ═══════════════════════════════════════════════════════════════
out.append("## 5. Block Bootstrap (100 runs)\n")
try:
    from tools.utils.research.block_bootstrap import run_block_bootstrap
    bb = run_block_bootstrap(PREFIX, PROFILE, iterations=100)
    # Filter to USDCHF-influenced runs is not straightforward with block bootstrap
    # since it resamples the full portfolio. Instead, we run sequence MC on USDCHF trades.
    out.append("*Note: Block bootstrap resamples the full portfolio. Using Sequence MC on USDCHF trades instead.*\n")
    mc = simulators.run_random_sequence_mc(tr_df, iterations=100, start_cap=start_cap)
    out.append(f"- Mean CAGR: {mc['cagr'].mean():.2f}%")
    out.append(f"- 5th pctl CAGR: {mc['cagr'].quantile(0.05):.2f}%")
    out.append(f"- Mean DD: {mc['max_dd_pct'].mean():.2f}%")
    out.append(f"- Worst DD: {mc['max_dd_pct'].max():.2f}%")
    below_start = (mc["final_equity"] < start_cap).sum()
    out.append(f"- Runs below start capital: {below_start} / 100 ({below_start}%)\n")
except Exception as e:
    # Fallback: just run the MC
    mc = simulators.run_random_sequence_mc(tr_df, iterations=100, start_cap=start_cap)
    out.append(f"- Mean CAGR: {mc['cagr'].mean():.2f}%")
    out.append(f"- 5th pctl CAGR: {mc['cagr'].quantile(0.05):.2f}%")
    out.append(f"- Mean DD: {mc['max_dd_pct'].mean():.2f}%")
    out.append(f"- Worst DD: {mc['max_dd_pct'].max():.2f}%")
    below_start = (mc["final_equity"] < start_cap).sum()
    out.append(f"- Runs below start capital: {below_start} / 100 ({below_start}%)\n")

# ═══════════════════════════════════════════════════════════════
# SECTION 6 — Verdict
# ═══════════════════════════════════════════════════════════════
out.append("## 6. Diagnostic Summary\n")
# Gather key facts for verdict
if raw_tl is not None:
    pnl_raw = raw_tl["pnl_usd"]
    gp_raw = pnl_raw[pnl_raw > 0].sum()
    gl_raw = abs(pnl_raw[pnl_raw < 0].sum())
    pf_check = gp_raw / gl_raw if gl_raw > 0 else 0
else:
    pf_check = 0

pf_pass = pf_check > 1.1
friction_pass = any(r["pf"] > 1.0 for r in results if "Severe" in r["scenario"])
cagr_5th = mc["cagr"].quantile(0.05)
bootstrap_pass = cagr_5th > 0

out.append("| Test | Result | Pass |")
out.append("|---|---|---|")
out.append(f"| Fixed-lot PF > 1.1 | {pf_check:.2f} | {'✅' if pf_pass else '❌'} |")
out.append(f"| Survives friction (Severe PF > 1.0) | {[r['pf'] for r in results if 'Severe' in r['scenario']][0]:.2f} | {'✅' if friction_pass else '❌'} |")
out.append(f"| Bootstrap 5th pctl CAGR > 0 | {cagr_5th:.2f}% | {'✅' if bootstrap_pass else '❌'} |")

# Rolling check
if raw_tl is not None:
    neg_frac = neg_windows / total_windows if total_windows > 0 else 1
    rolling_pass = neg_frac < 0.5
    out.append(f"| Rolling 1Y not structurally negative | {neg_frac*100:.1f}% negative | {'✅' if rolling_pass else '❌'} |")
else:
    rolling_pass = False

out.append("")
all_pass = pf_pass and friction_pass and bootstrap_pass and rolling_pass
if all_pass:
    out.append("**CONCLUSION: USDCHF shows a potentially CHF-specific breakout edge. Further OOS testing warranted.**")
else:
    out.append("**CONCLUSION: USDCHF edge does not survive all stress tests. Likely tail noise.**")

# ── Write report ──
report_content = "\n".join(out)
report_path = PROJECT_ROOT / "outputs" / "reports" / f"USDCHF_ISOLATION_{PREFIX}_{PROFILE}.md"
report_path.write_text(report_content, encoding="utf-8")

strat_path = PROJECT_ROOT / "strategies" / PREFIX / f"USDCHF_ISOLATION_{PREFIX}_{PROFILE}.md"
strat_path.write_text(report_content, encoding="utf-8")

print(f"[DONE] Report: {report_path}")
print(f"[DONE] Strategy copy: {strat_path}")
