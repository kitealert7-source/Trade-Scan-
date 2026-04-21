"""Portfolio evaluator constants (values only — no functions beyond matplotlib setup).

Centralizes capital model parameters, reliability floors, symbol/color palettes,
and the global matplotlib dark-theme configuration used by all report charts.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — must be set before pyplot import
import matplotlib.pyplot as plt

from config.state_paths import BACKTESTS_DIR, STRATEGIES_DIR
from tools.pipeline_utils import get_engine_version


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BACKTESTS_ROOT = BACKTESTS_DIR
STRATEGIES_ROOT = STRATEGIES_DIR

TOTAL_PORTFOLIO_CAPITAL = 10000.0
RISK_FREE_RATE = 0.0  # For Sharpe/Sortino
PORTFOLIO_ENGINE_VERSION = get_engine_version()
RELIABILITY_MIN_ACCEPTED = 50
RELIABILITY_MIN_SIM_YEARS = 1.0

SYMBOLS = ['AUS200', 'ESP35', 'EUSTX50', 'FRA40', 'GER40',
           'JPN225', 'NAS100', 'SPX500', 'UK100', 'US30']

# Color palette
COLORS = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
          '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9']

plt.rcParams.update({
    'figure.facecolor': '#1a1a2e',
    'axes.facecolor': '#16213e',
    'axes.edgecolor': '#0f3460',
    'axes.labelcolor': '#e0e0e0',
    'text.color': '#e0e0e0',
    'xtick.color': '#a0a0a0',
    'ytick.color': '#a0a0a0',
    'grid.color': '#0f3460',
    'grid.alpha': 0.3,
    'font.size': 10,
    'axes.titlesize': 13,
    'figure.titlesize': 15,
})
