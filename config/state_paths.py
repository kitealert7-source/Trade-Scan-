from pathlib import Path

# Repository Root
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Research State Root (Sibling to Repository)
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"

# Lifecycle Directories
RUNS_DIR = STATE_ROOT / "runs"
SANDBOX_DIR = STATE_ROOT / "sandbox"
CANDIDATES_DIR = STATE_ROOT / "candidates"
STRATEGIES_DIR = STATE_ROOT / "strategies"
REGISTRY_DIR = STATE_ROOT / "registry"
ARCHIVE_DIR = STATE_ROOT / "archive"
QUARANTINE_DIR = STATE_ROOT / "quarantine"
LOGS_DIR = STATE_ROOT / "logs"
BACKTESTS_DIR = STATE_ROOT / "backtests"
MASTER_FILTER_PATH = SANDBOX_DIR / "Strategy_Master_Filter.xlsx"
CANDIDATE_FILTER_PATH = CANDIDATES_DIR / "Filtered_Strategies_Passed.xlsx"

def initialize_state_directories():
    """Silent initialization of the research state infrastructure."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    
    directories = [
        RUNS_DIR,
        SANDBOX_DIR,
        CANDIDATES_DIR,
        STRATEGIES_DIR,
        REGISTRY_DIR,
        ARCHIVE_DIR,
        QUARANTINE_DIR,
        LOGS_DIR,
        BACKTESTS_DIR,
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
