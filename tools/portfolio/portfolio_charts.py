"""PNG chart generation — matplotlib isolated here."""

from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap

from tools.portfolio.portfolio_config import COLORS


def generate_charts(portfolio_equity, symbol_equity, corr_data, contributions,
                    stress_results, output_dir, strategy_id):
    """Generate all required PNG charts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Equity Curve ---
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(portfolio_equity.index, portfolio_equity.values,
            color='#00d4ff', linewidth=2, label='Portfolio')
    for i, (sym, eq) in enumerate(symbol_equity.items()):
        ax.plot(eq.index, eq.values, color=COLORS[i % len(COLORS)],
                linewidth=0.8, alpha=0.5, label=sym)
    ax.set_title(f'{strategy_id} - Portfolio Equity Curve', fontweight='bold')
    ax.set_ylabel('Equity (USD)')
    ax.legend(loc='upper left', fontsize=7, ncol=3)
    ax.grid(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    fig.tight_layout()
    fig.savefig(output_dir / 'equity_curve.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Drawdown Curve ---
    fig, ax = plt.subplots(figsize=(14, 4))
    running_max = portfolio_equity.cummax()
    dd_pct = (portfolio_equity - running_max) / running_max * 100
    ax.fill_between(dd_pct.index, dd_pct.values, 0,
                    color='#ff4757', alpha=0.6)
    ax.plot(dd_pct.index, dd_pct.values, color='#ff6b81', linewidth=0.8)
    ax.set_title(f'{strategy_id} - Portfolio Drawdown', fontweight='bold')
    ax.set_ylabel('Drawdown (%)')
    ax.grid(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    fig.tight_layout()
    fig.savefig(output_dir / 'drawdown_curve.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Correlation Heatmap ---
    corr_matrix = corr_data['corr_matrix']
    fig, ax = plt.subplots(figsize=(10, 8))
    cmap = LinearSegmentedColormap.from_list('custom', ['#2196F3', '#1a1a2e', '#FF5722'])
    im = ax.imshow(corr_matrix.values, cmap=cmap, vmin=-1, vmax=1, aspect='auto')
    ax.set_xticks(range(len(corr_matrix.columns)))
    ax.set_yticks(range(len(corr_matrix.index)))
    ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(corr_matrix.index, fontsize=9)
    for i in range(len(corr_matrix)):
        for j in range(len(corr_matrix)):
            val = corr_matrix.iloc[i, j]
            ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                    color='white', fontsize=8, fontweight='bold')
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(f'{strategy_id} - Correlation Matrix', fontweight='bold')
    fig.tight_layout()
    fig.savefig(output_dir / 'correlation_matrix.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Contribution Bar Chart ---
    fig, ax = plt.subplots(figsize=(12, 6))
    syms = list(contributions.keys())
    pnls = [contributions[s]['total_pnl'] for s in syms]
    colors_bar = ['#2ecc71' if p >= 0 else '#e74c3c' for p in pnls]
    bars = ax.bar(syms, pnls, color=colors_bar, edgecolor='#ffffff22', linewidth=0.5)
    for bar, val in zip(bars, pnls):
        ypos = bar.get_height() + (10 if val >= 0 else -30)
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'${val:.0f}', ha='center', fontsize=9, fontweight='bold')
    ax.set_title(f'{strategy_id} - PnL Contribution by Symbol', fontweight='bold')
    ax.set_ylabel('Net PnL (USD)')
    ax.axhline(y=0, color='#ffffff44', linewidth=0.8)
    ax.grid(True, axis='y')
    fig.tight_layout()
    fig.savefig(output_dir / 'contribution_chart.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Stress Test Chart ---
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    scenarios = list(stress_results.keys())
    for idx, metric in enumerate(['net_pnl', 'sharpe', 'return_dd']):
        vals = [stress_results[s][metric] for s in scenarios]
        labels = [s.replace('remove_', '-').replace('_', ' ') for s in scenarios]
        colors_stress = ['#00d4ff' if i == 0 else '#ffaa00' for i in range(len(vals))]
        axes[idx].barh(labels, vals, color=colors_stress, edgecolor='#ffffff22')
        axes[idx].set_title(metric.replace('_', ' ').title(), fontweight='bold')
        axes[idx].grid(True, axis='x')
        for i, v in enumerate(vals):
            xoff = abs(max(vals) - min(vals)) * 0.05 if max(vals) != min(vals) else 1
            axes[idx].text(v + (xoff if v >= 0 else -xoff),
                          i, f'{v:.0f}' if metric != 'sharpe' else f'{v:.2f}',
                          va='center', fontsize=8)
    fig.suptitle(f'{strategy_id} - Stress Test Results', fontweight='bold', fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / 'stress_test_chart.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    print(f"  [CHARTS] 5 charts saved to {output_dir}")
