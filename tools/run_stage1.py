"""
run_stage1.py — Minimal Stage-1 Execution Harness (Multi-Asset Batch v4)
Purpose: Execute Directive (Batch), emit Stage-1 artifacts only
Authority: SOP_TESTING, SOP_OUTPUT

NO METRICS COMPUTATION
NO STAGE-2 OR STAGE-3
"""

import sys
import uuid
import json
import hashlib
import csv
import traceback
import re
from pathlib import Path
from datetime import datetime
import yaml
import pandas as pd
import numpy as np

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- CONFIGURATION TO BE PARSED FROM DIRECTIVE ---
# Default placeholders, will be overridden by parsing
DIRECTIVE_FILENAME = "SPX04.txt"
BROKER = "OctaFx"
TIMEFRAME = "1d"
START_DATE = "2015-01-01"
END_DATE = "2026-01-31"



# --- PnL NORMALIZATION LOGIC ---

# Module-level cache for Close prices: (symbol, date_str) -> close_price
CONVERSION_CACHE = {}

def parse_symbol_properties(symbol: str):
    """
    Parse symbol into base and quote currencies.
    - 6-char symbols (e.g. EURUSD) -> Base=EUR, Quote=USD
    - 6+ chars ending in USD (e.g. XAUUSD) -> Base=XAU, Quote=USD
    - Others -> Non-FX (Base=Symbol, Quote=None)
    """
    s = symbol.upper()
    if len(s) == 6:
        return s[:3], s[3:]
    elif s.endswith("USD"):
        return s[:-3], "USD"
    else:
        return s, None

# Global DF Cache for conversion pairs: symbol -> DF
_CONVERSION_DF_CACHE = {}

def get_conversion_price_at_time(target_pair: str, timestamp: pd.Timestamp) -> float:
    """
    Fetch price from cached dataframe.
    """
    if target_pair not in _CONVERSION_DF_CACHE:
        try:
            # Re-use load_market_data but we need to ensure global Start/End dates cover it.
            # We will use the global START_DATE/END_DATE.
            print(f"[CONVERSION] Loading data for {target_pair}...")
            df = load_market_data(target_pair)
            
            # Optimization: Keep only timestamp and close
            df = df[['timestamp', 'close']].copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            
            _CONVERSION_DF_CACHE[target_pair] = df
        except Exception as e:
            # Allow failure if file doesn't exist, caller handles retry logic
            raise ValueError(f"Failed to load conversion pair {target_pair}: {e}")
            
    df = _CONVERSION_DF_CACHE[target_pair]
    
    # As-of lookup (nearest previous close)
    try:
        # idx = df.index.get_indexer([timestamp], method='ffill')[0]
        # Using asof is cleaner for singular lookups
        # converting timestamp to index type (DatetimeIndex)
        ts = pd.Timestamp(timestamp)
        idx = df.index.asof(ts)
        
        if pd.isna(idx):
             raise ValueError("Date out of range (before start)")
             
        val = df.loc[idx]['close']
        if isinstance(val, pd.Series):
            val = val.iloc[0] # handle duplicates if any
        return float(val)
    except Exception as e:
        raise ValueError(f"No data found for {target_pair} at {timestamp}: {e}")

def normalize_pnl_to_usd(raw_pnl_quote: float, 
                         base_ccy: str, 
                         quote_ccy: str, 
                         exit_price: float, 
                         timestamp: pd.Timestamp) -> float:
    """
    Normalize PnL to USD using exact case logic.
    """
    # Case A: Quote is USD (e.g. EURUSD, GBPUSD, XAUUSD)
    if quote_ccy == "USD":
        return raw_pnl_quote
        
    # Case B: Base is USD (e.g. USDJPY, USDCAD, USDCHF)
    if base_ccy == "USD":
        if exit_price == 0: return 0.0
        return raw_pnl_quote / exit_price
    
    # Check if we failed parsing or non-fx
    if quote_ccy is None:
        # Case D: Non-FX -> Pass-through
        return raw_pnl_quote
        
    # Case C: Cross Pair (e.g. EURGBP)
    # Target: Convert Quote (GBP) to USD.
    # Method 1: {Quote}USD (e.g. GBPUSD) -> Multiplier
    # Method 2: USD{Quote} (e.g. USDGBP - Rare) -> Divisor
    
    target_direct = f"{quote_ccy}USD"
    target_indirect = f"USD{quote_ccy}"
    
    # Try Direct
    try:
        rate = get_conversion_price_at_time(target_direct, timestamp)
        return raw_pnl_quote * rate
    except ValueError:
        pass
        
    # Try Indirect
    try:
        rate = get_conversion_price_at_time(target_indirect, timestamp)
        return raw_pnl_quote / rate
    except ValueError:
        pass
        
    # Hard Fail
    raise ValueError(f"Missing conversion data for cross PnL ({base_ccy}/{quote_ccy}). Needed {target_direct} or {target_indirect}.")


def get_engine_version():
    """Dynamically import engine module and read __version__."""
    import importlib.util

    engine_path = PROJECT_ROOT / "engine_dev/universal_research_engine/1.2.0/main.py"
    if not engine_path.exists():
        raise RuntimeError(f"Engine main.py not found at {engine_path}")

    spec = importlib.util.spec_from_file_location("universal_research_engine", engine_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load engine spec")
        
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "__version__"):
        raise RuntimeError("Engine module missing __version__ attribute")

    return module.__version__


def parse_directive(file_path: Path) -> dict:
    """
    Parse directive text into a structured dictionary for canonical hashing.
    Supports 'Key: Value' and Lists (- item or implicit).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    parsed = {}
    current_key = None
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
            
        # List Item (Explicit)
        if line.startswith("-") and current_key:
            val = line[1:].strip()
            if not isinstance(parsed[current_key], list):
                parsed[current_key] = []
            parsed[current_key].append(val)
            continue
            
        # Key-Value
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            if not val:
                # Key with empty value, possibly start of list
                parsed[key] = []
                current_key = key
            else:
                parsed[key] = val
                current_key = key
        else:
            # Implicit List Item (No dash, no colon, but we have a current_key pointing to a list)
            if current_key and isinstance(parsed.get(current_key), list):
                parsed[current_key].append(line)
            else:
                # Continuation text or description, ignore for config hash if not Key:Value
                pass
            
    return parsed


def get_canonical_hash(parsed_data: dict) -> str:
    """Generate SHA256 hash of canonical JSON representation."""
    canonical_str = json.dumps(parsed_data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical_str.encode()).hexdigest()[:8]


def load_market_data(symbol: str) -> pd.DataFrame:
    """Load Daily data from MASTER_DATA for efficient batching."""
    # Dynamic path construction
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / f"{symbol}_{BROKER.upper()}_MASTER" / "RESEARCH"
    
    # Files are split by year. Pattern: SYMBOL_BROKER_TIMEFRAME_YYYY_RESEARCH.csv
    pattern = f"{symbol}_{BROKER.upper()}_{TIMEFRAME}_*_RESEARCH.csv"
    files = sorted(data_root.glob(pattern))
    
    if not files:
        raise FileNotFoundError(f"No RESEARCH market data found for {symbol} / {BROKER} / {TIMEFRAME} in {data_root}")
    
    dfs = [pd.read_csv(f, comment='#') for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    if 'time' in df.columns:
        df['timestamp'] = df['time']
    
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Filter
    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)
    
    print(f"[DATA] {symbol}: Loaded {len(df)} bars")
    return df


def load_broker_spec(symbol: str) -> dict:
    """Load broker specification for symbol."""
    broker_spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / BROKER / f"{symbol}.yaml"
    if not broker_spec_path.exists():
        print(f"[DEBUG] Failed Path: '{broker_spec_path}' (Absolute: {broker_spec_path.absolute()})")
        print(f"[DEBUG] BROKER='{BROKER}', symbol='{symbol}'")
        raise FileNotFoundError(f"Broker spec not found: {broker_spec_path}")
    
    with open(broker_spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
        
    required = ["contract_size", "min_lot"]
    for field in required:
        if field not in spec or spec[field] is None:
            raise ValueError(f"Broker spec missing mandatory field: {field}")
            
    return spec


def load_strategy(strategy_id: str):
    """Dynamically load strategy plugin."""
    import importlib
    
    # Validation
    plugin_path = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if not plugin_path.exists():
        raise FileNotFoundError(f"Strategy plugin not found: {plugin_path}")

    # --- STATIC ANALYSIS GUARD ---
    source_code = plugin_path.read_text(encoding='utf-8')
    forbidden = ["rolling(", "high_low", "high_close"]
    for term in forbidden:
        if term in source_code:
            raise RuntimeError(f"Inline indicator logic detected ('{term}'). Use repository indicators.")
    # -----------------------------

    # -----------------------------

    # --- INDICATOR DEPENDENCY VALIDATION ---
    import re

    # reuse source_code from above

    # Match: from indicators.<domain>.<module> import <name>
    pattern = r"from\s+indicators\.([a-zA-Z0-9_\.]+)\s+import\s+([a-zA-Z0-9_,\s]+)"

    matches = re.findall(pattern, source_code)

    for module_path, imported_names in matches:
        module_parts = module_path.split(".")
        indicator_file = PROJECT_ROOT / "indicators" / Path(*module_parts).with_suffix(".py")

        if not indicator_file.exists():
            raise RuntimeError(
                f"Indicator dependency missing: indicators/{module_path}.py"
            )

    # ----------------------------------------
        
    module_path = f"strategies.{strategy_id}.strategy"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        # Fallback for when current directory is not in path correctly or package issues
        import importlib.util
        spec = importlib.util.spec_from_file_location("strategy_plugin", plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    StrategyClass = getattr(module, "Strategy", None)
    if StrategyClass is None:
        raise ValueError(f"Strategy class not found in {module_path}")
        
    return StrategyClass()


def run_engine_logic(df, strategy):
    """Run engine execution loop."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "execution_loop",
        PROJECT_ROOT / "engine_dev/universal_research_engine/1.2.0/execution_loop.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_execution_loop(df, strategy)


def emit_result(trades, df, broker_spec, symbol, run_id, content_hash, lineage_str, directive_content, median_bar_seconds=0):
    """Emit artifacts for a single symbol run."""
    import pandas as pd
    from tools.execution_emitter_stage1 import emit_stage1, RawTradeRecord, Stage1Metadata
    
    contract_size = float(broker_spec["contract_size"])
    min_lot = float(broker_spec["min_lot"])
    
    raw_trades = []
    for i, t in enumerate(trades):
        entry = t['entry_price']
        exit_p = t['exit_price']
        direction = t['direction'] if t['direction'] != 0 else 1
        # Volatility-weighted sizing: if strategy prepared a size_multiplier column,
        # use it at the trade's entry index to scale position size.
        entry_idx_for_size = t["entry_index"]
        if 'size_multiplier' in df.columns:
            multiplier = df.iloc[entry_idx_for_size].get('size_multiplier', 1.0)
            if pd.isna(multiplier):
                multiplier = 1.0
            size_lots = min_lot * multiplier
        else:
            size_lots = t.get('size', min_lot)
        units = size_lots * contract_size
        # --- PnL Calculation (Currency Aware) ---
        base_ccy, quote_ccy = parse_symbol_properties(symbol)
        
        # Raw PnL in Quote Currency
        raw_pnl_quote = (exit_p - entry) * direction * units
        
        try:
            pnl_usd = normalize_pnl_to_usd(
                raw_pnl_quote=raw_pnl_quote,
                base_ccy=base_ccy,
                quote_ccy=quote_ccy,
                exit_price=exit_p,
                timestamp=pd.Timestamp(t['exit_timestamp']) # Ensure Timestamp type
            )
        except ValueError as e:
            # Propagate error with context
            raise ValueError(f"[PnL Fail] Trade {i+1} on {symbol}: {e}")
            
        # Notional is harder for Cross pairs. 
        # For now, approximate:
        # - If Quote=USD, Notional = Units * Entry
        # - If Base=USD, Notional = Units
        # - Cross? We need valid Notional in USD for ROI calc.
        # Let's use similar logic or simplified approximation:
        # If Base=USD, Notional is Units.
        # Else, Notional = Units * Entry (amount in Quote) -> Convert Quote to USD.
        
        # Simplification for Notional:
        if base_ccy == "USD":
            notional_usd = units
        elif quote_ccy == "USD":
            notional_usd = units * entry
        else:
            # Cross/Other: Convert Notional(Quote) to USD
            # notional_quote = units * entry
            # reuse normalize logic? 
            # normalize_pnl handles "Amount in Quote -> USD" conversion.
            # So yes:
            try:
                notional_usd = normalize_pnl_to_usd(
                    raw_pnl_quote=(units * entry),
                    base_ccy=base_ccy,
                    quote_ccy=quote_ccy,
                    exit_price=exit_p, # Proxy: using exit price for rate lookup might be slight mismatch for Entry Notional 
                                       # but for Cross Rate conversion (e.g. GBPUSD) it typically uses CURRENT rate (exit time).
                                       # Acceptable for Stage-1.
                    timestamp=pd.Timestamp(t['entry_timestamp']) # Use entry time for Notional?
                )
            except ValueError:
                notional_usd = 0.0 # Fallback

        
        entry_idx = t["entry_index"]
        exit_idx = t["exit_index"]
        slice_df = df.iloc[entry_idx:exit_idx + 1]
        trade_high = slice_df["high"].max()
        trade_low = slice_df["low"].min()

        if direction == 1:
            mfe_price = trade_high - entry
            mae_price = entry - trade_low
        else:
            mfe_price = entry - trade_low
            mae_price = trade_high - entry
        
        risk_price = 0.0 # No SL
        
        raw_trades.append(RawTradeRecord(
            strategy_name=f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}",
            parent_trade_id=i + 1,
            sequence_index=i,
            entry_timestamp=str(t['entry_timestamp']),
            exit_timestamp=str(t['exit_timestamp']),
            direction=direction,
            entry_price=entry,
            exit_price=exit_p,
            bars_held=t['bars_held'],
            pnl_usd=round(pnl_usd, 2),
            trade_high=trade_high,
            trade_low=trade_low,
            atr_entry=t.get('atr'),
            position_units=units,
            notional_usd=round(notional_usd, 2),
            mfe_price=round(mfe_price, 4),
            mae_price=round(mae_price, 4),
            mfe_r=0.0,
            mae_r=0.0,
            r_multiple=0.0
        ))
    
    # Metadata includes Deterministic Run details
    metadata = Stage1Metadata(
        run_id=run_id,
        strategy_name=f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}",
        symbol=symbol,
        timeframe=TIMEFRAME,
        date_range_start=START_DATE,
        date_range_end=END_DATE,
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="Universal_Research_Engine",
        engine_version=get_engine_version(),
        broker=BROKER,
        reference_capital_usd=float(broker_spec["reference_capital_usd"])
    )
    
    # Inject lineage into metadata (Hack: using a field or just logging it? 
    # SOP Schema might not have 'lineage_string'. Emitter writes json via asdict. 
    # We can't easily add fields to dataclass without changing Emitter.
    # But user requested "Metadata must include... lineage_string".
    # I will modify the emitter in memory or just accept it's missing from JSON for now,
    # OR rely on `batch_summary` or `run_metadata.json` if Emitter allows extra fields.
    # The Emitter takes `Stage1Metadata` dataclass.
    # I will strictly follow Emitter for now to avoid breaking it.)
    
    output_root = PROJECT_ROOT / "backtests"
    
    # Directive filename for backup: {DIRECTIVE}_{SYMBOL}.txt
    out_name = f"{DIRECTIVE_FILENAME.replace('.txt', '')}_{symbol}.txt"
    
    out_folder = emit_stage1(raw_trades, metadata, directive_content, out_name, output_root, median_bar_seconds)

    # PATCH 3: Enriched Metadata Injection (Post-Emission)
    meta_path = out_folder / "metadata" / "run_metadata.json"
    if meta_path.exists():
        with open(meta_path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data['content_hash'] = content_hash
            data['lineage_string'] = lineage_str
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()
            
    return out_folder


def main():
    print("=" * 60)
    print("MULTI-ASSET BATCH EXECUTION HARNESS (v4)")
    print("=" * 60)
    
    global DIRECTIVE_FILENAME, BROKER, TIMEFRAME, START_DATE, END_DATE

    # 1a. Validate Environment
    indicators_root = PROJECT_ROOT / "indicators"
    if not indicators_root.exists():
        print(f"[FATAL] Indicators repository missing at {indicators_root}")
        return

    # 1. Locate Directive (with Argument Support)
    import argparse
    parser = argparse.ArgumentParser(description="Stage-1 Execution Harness")
    parser.add_argument("directive", nargs="?", help="Optional Directive ID (e.g. IDX28)")
    args = parser.parse_args()

    active_dir = PROJECT_ROOT / "backtest_directives" / "active"
    
    if args.directive:
        # Argument Mode
        candidate = args.directive.replace(".txt", "")
        directive_path = active_dir / f"{candidate}.txt"
        if not directive_path.exists():
            # Try exact match if user provided extension
            directive_path = active_dir / candidate 
            if not directive_path.exists():
                print(f"[FATAL] Specified directive not found: {directive_path}")
                return
    else:
        # Legacy Mode (Single File Auto-Detect)
        txt_files = list(active_dir.glob("*.txt"))
        if len(txt_files) != 1:
            print(f"[FATAL] Expected exactly 1 active directive, found {len(txt_files)}.")
            return
        directive_path = txt_files[0]

    global DIRECTIVE_FILENAME
    DIRECTIVE_FILENAME = directive_path.name
    print(f"[INIT] Directive: {DIRECTIVE_FILENAME}")
    
    # 2. Parse & Canonical Hash
    directive_content = directive_path.read_text(encoding="utf-8")
    parsed_config = parse_directive(directive_path)
    
    # --- CRITICAL FIX: Update Globals from Directive ---
    if "Broker" in parsed_config: BROKER = parsed_config["Broker"]
    if "Timeframe" in parsed_config: TIMEFRAME = parsed_config["Timeframe"]
    if "Start Date" in parsed_config: START_DATE = parsed_config["Start Date"]
    if "End Date" in parsed_config: END_DATE = parsed_config["End Date"]
    
    # --- Inject resolved defaults into canonical config ---
    resolved_config = dict(parsed_config)  # shallow copy
    
    resolved_config.update({
        "BROKER": BROKER,
        "TIMEFRAME": TIMEFRAME,
        "START_DATE": START_DATE,
        "END_DATE": END_DATE
    })
    
    content_hash = get_canonical_hash(resolved_config)
    print(f"[INIT] Content Hash: {content_hash}")
    
    # 3. Engine Version
    engine_ver = get_engine_version()
    print(f"[INIT] Engine Version: {engine_ver}")
    
    # 4a. Get Strategy ID
    strategy_id = parsed_config.get("Strategy")
    if not strategy_id:
        print("[FATAL] Directive missing 'Strategy' field.")
        return
    print(f"[CONFIG] Strategy ID: {strategy_id}")

    # 4b. Get Symbols
    symbols = parsed_config.get("Symbols", [])
    if isinstance(symbols, str):
        symbols = [symbols]
    if not symbols:
        print("[FATAL] No symbols define in directive.")
        return
        
    print(f"[CONFIG] Batch Size: {len(symbols)} symbols ({symbols})")

    # 5. Batch Loop
    summary_csv = PROJECT_ROOT / "backtests" / f"batch_summary_{DIRECTIVE_FILENAME.replace('.txt', '')}.csv"
    batch_results = []
    
    for symbol in symbols:
        print(f"\n>>> PROCESSING: {symbol} ...")
        
        status = "FAILED"
        run_id = "N/A"
        net_pnl = 0.0
        error_msg = ""
        
        try:
            # Deterministic Run ID
            # lineage_str = f"{content_hash}_{symbol}_{timeframe}_{broker}_{engine_version}"
            lineage_str = f"{content_hash}_{symbol}_{TIMEFRAME}_{BROKER}_{engine_ver}"
            run_id = hashlib.sha256(lineage_str.encode()).hexdigest()[:12]
            print(f"    Run ID: {run_id}")
            
            # Load Data
            df = load_market_data(symbol)
            broker_spec = load_broker_spec(symbol)
            
            # --- METRIC INTEGRITY: Compute Bar Geometry ---
            median_bar_seconds = 0
            if len(df) > 1:
                deltas = df["timestamp"].diff().dropna().dt.total_seconds()
                median_bar_seconds = int(deltas.median()) if not deltas.empty else 0
            
            print(f"    Geometry: {median_bar_seconds}s per bar")
            
            # Strategy
            strategy = load_strategy(strategy_id)
            
            # Exec
            trades = run_engine_logic(df, strategy)
            print(f"    Trades: {len(trades)}")
            
            # Emit
            if trades:
                out_folder = emit_result(trades, df, broker_spec, symbol, run_id, content_hash, lineage_str, directive_content, median_bar_seconds)
                
                # Persist Strategy
                from pathlib import Path
                # Persist Strategy Source (Full Module Snapshot)
                from pathlib import Path
                import shutil

                target_dir = PROJECT_ROOT / "runs" / run_id
                target_dir.mkdir(parents=True, exist_ok=True)

                # Source plugin file
                plugin_file = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"

                if not plugin_file.exists():
                    raise FileNotFoundError(f"Cannot snapshot strategy — file missing: {plugin_file}")

                # Copy full module file verbatim
                shutil.copy2(plugin_file, target_dir / "strategy.py")
                
                contract_size = float(broker_spec["contract_size"])
                min_lot = float(broker_spec["min_lot"])
                has_mult = 'size_multiplier' in df.columns
                total_pnl = 0.0
                
                # --- Batch Summary PnL (Currency Aware) ---
                base_ccy, quote_ccy = parse_symbol_properties(symbol)
                
                for t in trades:
                    d = t['direction'] if t['direction'] != 0 else 1
                    if has_mult:
                        m = df.iloc[t['entry_index']].get('size_multiplier', 1.0)
                        import math
                        if math.isnan(m): m = 1.0
                        sl = min_lot * m
                    else:
                        sl = t.get('size', min_lot)
                    
                    units = sl * contract_size
                    raw_pnl_quote = (t['exit_price'] - t['entry_price']) * d * units
                    
                    try:
                        trade_pnl = normalize_pnl_to_usd(
                            raw_pnl_quote=raw_pnl_quote,
                            base_ccy=base_ccy,
                            quote_ccy=quote_ccy,
                            exit_price=t['exit_price'],
                            timestamp=pd.Timestamp(t['exit_timestamp'])
                        )
                        total_pnl += trade_pnl
                    except ValueError:
                        # For batch summary, if cross conversion fails, maybe warn or skip?
                        # User requested strictness, but failing the whole batch might be harsh.
                        # Let's log and skip trade to minimize noise, or just fail as per strict req?
                        # Req: "Hard raise if neither cross pair exists." -> So we let it crash.
                        raise
                        
                net_pnl = total_pnl
                
                status = "SUCCESS"
                print(f"    [SUCCESS] Artifacts: {out_folder}")
            else:
                status = "NO_TRADES"
                print("    [WARN] No trades generated.")

        except Exception as e:
            error_msg = str(e)
            print(f"    [ERROR] {e}")
            # traceback.print_exc()

        batch_results.append({
            "Symbol": symbol,
            "RunID": run_id,
            "Status": status,
            "NetPnL": round(net_pnl, 2),
            "Error": error_msg
        })

    # 6. Write Summary
    print("\n" + "=" * 60)
    print("BATCH EXECUTION SUMMARY")
    print("=" * 60)
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Symbol", "RunID", "Status", "NetPnL", "Error"])
        writer.writeheader()
        for res in batch_results:
            writer.writerow(res)
            print(f"{res['Symbol']:<10} | {res['Status']:<10} | {res['RunID']:<12} | PnL: ${res['NetPnL']}")
            
    print("=" * 60)

if __name__ == "__main__":
    main()
