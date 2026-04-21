"""Equity-curve + overlay comparison plots (visualization only, no artifact writing)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from tools.capital.capital_portfolio_state import PortfolioState


def plot_equity_curve(state: PortfolioState, output_dir: Path) -> None:
    """Render equity-curve + drawdown chart and save as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless â€” no display required
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib not installed â€” skipping equity curve plot.")
        return

    if not state.equity_timeline:
        return

    timestamps = [ts for ts, _ in state.equity_timeline]
    equity     = [eq for _, eq in state.equity_timeline]

    # Convert to pandas for resampling convenience
    import pandas as pd
    eq_series = pd.Series(equity, index=pd.to_datetime(timestamps))
    eq_series = eq_series[~eq_series.index.duplicated(keep="last")]
    daily     = eq_series.resample("D").last().ffill()

    peak    = daily.cummax()
    dd_pct  = ((daily - peak) / peak) * 100   # negative values

    dates = daily.index.to_pydatetime()

    # â”€â”€ Layout: 2 rows, shared x-axis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fig, (ax_eq, ax_dd) = plt.subplots(
        2, 1,
        figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
        facecolor="#0d0d12",
    )
    fig.subplots_adjust(hspace=0.05)

    profile_label = state.profile_name
    start_cap     = state.starting_capital
    final_eq      = daily.iloc[-1]

    # â”€â”€ Upper panel: equity curve â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ax_eq.set_facecolor("#0d0d12")
    ax_eq.plot(dates, daily.values, color="#00d4aa", linewidth=1.4, zorder=3)
    ax_eq.fill_between(dates, start_cap, daily.values,
                        where=(daily.values >= start_cap),
                        alpha=0.15, color="#00d4aa", zorder=2)
    ax_eq.axhline(start_cap, color="#555", linewidth=0.8, linestyle="--")

    ax_eq.set_yscale("log")
    ax_eq.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    ax_eq.set_ylabel("Portfolio Equity (log)", color="#ccc", fontsize=11)
    ax_eq.tick_params(colors="#999", labelsize=9)
    ax_eq.spines[:].set_color("#222")
    ax_eq.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)

    # Title
    ax_eq.set_title(
        f"{profile_label}  |  ${start_cap:,.0f}  â†’  ${final_eq:,.0f}",
        color="#eee", fontsize=13, pad=10,
    )

    # â”€â”€ Lower panel: drawdown â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ax_dd.set_facecolor("#0d0d12")
    ax_dd.fill_between(dates, dd_pct.values, 0,
                        where=(dd_pct.values < 0),
                        color="#e05252", alpha=0.7, zorder=2)
    ax_dd.plot(dates, dd_pct.values, color="#e05252", linewidth=0.9, zorder=3)
    ax_dd.axhline(0, color="#555", linewidth=0.8)

    ax_dd.set_ylabel("Drawdown %", color="#ccc", fontsize=10)
    ax_dd.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1f}%")
    )
    ax_dd.tick_params(colors="#999", labelsize=9)
    ax_dd.spines[:].set_color("#222")
    ax_dd.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)

    # X-axis formatting (shared)
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dd.tick_params(axis="x", colors="#999", labelsize=9)

    out_path = output_dir / "equity_curve.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[EMIT] {state.profile_name} equity curve plot -> {out_path}")


def plot_overlay_comparison(states: Dict[str, "PortfolioState"], output_root: Path) -> None:
    """Render a single normalized-linear overlay comparing all profiles on shared axes.

    Individual equity_curve.png files use log-scale and look visually identical across
    profiles because every profile consumes the same R-series. This overlay plots each
    profile normalized to starting_capital=1.0 on a LINEAR axis so magnitude divergence
    (the real signal) is visible in one frame.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import pandas as pd
    except ImportError:
        print("[WARN] matplotlib not installed — skipping overlay comparison plot.")
        return

    if not states:
        return

    palette = [
        "#00d4aa", "#ff7043", "#42a5f5", "#ab47bc",
        "#ffca28", "#8d6e63", "#bdbdbd", "#ef5350",
        "#26c6da", "#d4e157",
    ]

    fig, (ax_eq, ax_dd) = plt.subplots(
        2, 1, figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True, facecolor="#0d0d12",
    )
    fig.subplots_adjust(hspace=0.05)
    ax_eq.set_facecolor("#0d0d12")
    ax_dd.set_facecolor("#0d0d12")

    # REAL_MODEL_V1 rendered thick so it stands out if present.
    ordered = sorted(states.items(), key=lambda kv: 0 if kv[0] == "REAL_MODEL_V1" else 1)

    for i, (name, state) in enumerate(ordered):
        if not state.equity_timeline:
            continue
        ts = [t for t, _ in state.equity_timeline]
        eq = [e for _, e in state.equity_timeline]
        s = pd.Series(eq, index=pd.to_datetime(ts))
        s = s[~s.index.duplicated(keep="last")]
        daily = s.resample("D").last().ffill()
        start = state.starting_capital if state.starting_capital > 0 else daily.iloc[0]
        norm = daily / start
        peak = daily.cummax()
        dd = (daily / peak - 1.0) * 100.0

        color = palette[i % len(palette)]
        lw = 2.2 if name == "REAL_MODEL_V1" else 1.2
        alpha = 1.0 if name == "REAL_MODEL_V1" else 0.85
        label = f"{name}  ({norm.iloc[-1]:.2f}x, DD {dd.min():.1f}%)"
        ax_eq.plot(daily.index.to_pydatetime(), norm.values,
                   color=color, linewidth=lw, alpha=alpha, label=label, zorder=3)
        ax_dd.plot(daily.index.to_pydatetime(), dd.values,
                   color=color, linewidth=lw * 0.7, alpha=alpha, zorder=3)

    ax_eq.axhline(1.0, color="#555", linewidth=0.8, linestyle="--")
    ax_eq.set_ylabel("Equity (normalized, start = 1.0×)", color="#ccc", fontsize=11)
    ax_eq.set_title(
        "Profile Overlay — normalized linear equity × drawdown",
        color="#eee", fontsize=13, pad=10,
    )
    ax_eq.tick_params(colors="#999", labelsize=9)
    ax_eq.spines[:].set_color("#222")
    ax_eq.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)
    leg = ax_eq.legend(loc="upper left", facecolor="#15151c",
                       edgecolor="#333", labelcolor="#ddd", fontsize=9, framealpha=0.9)
    for t in leg.get_texts():
        t.set_color("#ddd")

    ax_dd.axhline(0, color="#555", linewidth=0.8)
    ax_dd.set_ylabel("Drawdown %", color="#ccc", fontsize=10)
    ax_dd.tick_params(colors="#999", labelsize=9)
    ax_dd.spines[:].set_color("#222")
    ax_dd.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    out_path = output_root / "overlay_comparison.png"
    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[EMIT] Overlay comparison -> {out_path}")
